import json
import random
import select
import subprocess
import sys
import time
from pathlib import Path

# ====== 設定ここから ======

CONFIG_PATH = Path(__file__).with_name("config.json")
CACHE_PATH = Path(__file__).with_name("tracks_cache.json")
HISTORY_LIMIT = 20

DEFAULT_CONFIG = {
    "playlist_name": "",
    "default_weight": 10,
    "artist_weights": {},
    "track_weights": {},
    "avoid_immediate_repeat": True,
    "check_interval": 0.2,
}

# ====== 設定ここまで ======


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            "config.json が見つかりません。"
            " config.example.json をコピーして config.json を作ってください。"
        )

    with CONFIG_PATH.open(encoding="utf-8") as f:
        user_config = json.load(f)

    config = DEFAULT_CONFIG | user_config

    if not config["playlist_name"]:
        raise ValueError("config.json の playlist_name を設定してください。")

    return config


CONFIG = load_config()
PLAYLIST_NAME = CONFIG["playlist_name"]
DEFAULT_WEIGHT = CONFIG["default_weight"]
ARTIST_WEIGHTS = CONFIG["artist_weights"]
TRACK_WEIGHTS = CONFIG["track_weights"]
AVOID_IMMEDIATE_REPEAT = CONFIG["avoid_immediate_repeat"]
CHECK_INTERVAL = CONFIG["check_interval"]


def osa_string(s: str) -> str:
    """AppleScript用の文字列エスケープ"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def run_osascript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.strip()


def prepare_music():
    script = """
    tell application "Music"
        activate
        try
            set shuffle enabled to false
        end try
    end tell
    """
    run_osascript(script)


def load_tracks_from_music():
    script = f"""
    set playlistName to {osa_string(PLAYLIST_NAME)}

    tell application "Music"
        set p to playlist playlistName
        set outText to ""

        repeat with i from 1 to count of tracks of p
            try
                set t to track i of p
                set pid to persistent ID of t
                set trackName to name of t
                set artistName to artist of t
                set outText to outText & i & tab & pid & tab & trackName & tab & artistName & linefeed
            end try
        end repeat

        return outText
    end tell
    """

    output = run_osascript(script)
    tracks = []

    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 4:
            tracks.append({
                "index": int(parts[0]),
                "id": parts[1],
                "name": parts[2],
                "artist": parts[3],
            })

    return tracks


def read_tracks_cache():
    if not CACHE_PATH.exists():
        return None

    try:
        with CACHE_PATH.open(encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    if cache.get("playlist_name") != PLAYLIST_NAME:
        return None

    tracks = cache.get("tracks")
    if not isinstance(tracks, list):
        return None

    required_keys = {"index", "id", "name", "artist"}
    if not all(isinstance(track, dict) and required_keys <= track.keys() for track in tracks):
        return None

    return tracks


def write_tracks_cache(tracks):
    cache = {
        "playlist_name": PLAYLIST_NAME,
        "tracks": tracks,
    }

    with CACHE_PATH.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_tracks(force_reload=False):
    if not force_reload:
        cached_tracks = read_tracks_cache()
        if cached_tracks is not None:
            print(f"{CACHE_PATH.name} から曲リストを読み込みました。")
            return cached_tracks

    print("Musicから曲リストを読み込んでいます...")
    tracks = load_tracks_from_music()
    write_tracks_cache(tracks)
    print(f"{CACHE_PATH.name} を更新しました。")
    return tracks


def get_weight(track):
    name = track["name"]
    artist = track["artist"]

    if name in TRACK_WEIGHTS:
        return TRACK_WEIGHTS[name]

    if artist in ARTIST_WEIGHTS:
        return ARTIST_WEIGHTS[artist]

    return DEFAULT_WEIGHT


def pick_track(tracks, last_id=None):
    candidates = tracks

    if AVOID_IMMEDIATE_REPEAT and last_id is not None and len(tracks) > 1:
        candidates = [t for t in tracks if t["id"] != last_id]

    weights = [get_weight(t) for t in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def play_track(track):
    script = f"""
    set playlistName to {osa_string(PLAYLIST_NAME)}
    set targetIndex to {track["index"]}

    tell application "Music"
        set p to playlist playlistName

        if targetIndex > (count of tracks of p) then
            error "曲が見つかりません: " & targetIndex
        end if

        play track targetIndex of p
    end tell
    """
    run_osascript(script)


def pause_music():
    script = """
    tell application "Music"
        pause
    end tell
    """
    run_osascript(script)


def resume_music():
    script = """
    tell application "Music"
        play
    end tell
    """
    run_osascript(script)


def stop_music():
    script = """
    tell application "Music"
        stop
    end tell
    """
    run_osascript(script)


def toggle_pause_or_resume(track, manually_stopped):
    status = get_player_status()

    if status["state"] == "playing":
        pause_music()
        print("一時停止")
        return False

    if manually_stopped or status["state"] == "stopped":
        play_track(track)
    else:
        resume_music()

    print(f"再生再開: {format_track(track)}")
    return False


def get_player_status():
    script = """
    tell application "Music"
        set outText to (player state as text)

        try
            set outText to outText & "|||" & (persistent ID of current track as text)
        on error
            set outText to outText & "|||"
        end try

        try
            set outText to outText & "|||" & (player position as text)
        on error
            set outText to outText & "|||0"
        end try

        return outText
    end tell
    """

    output = run_osascript(script)
    parts = output.split("|||")

    state = parts[0] if len(parts) > 0 else "unknown"
    track_id = parts[1] if len(parts) > 1 and parts[1] else None

    try:
        position = float(parts[2]) if len(parts) > 2 else 0.0
    except ValueError:
        position = 0.0

    return {
        "state": state,
        "id": track_id,
        "position": position,
    }


def read_terminal_command():
    readable, _, _ = select.select([sys.stdin], [], [], 0)
    if not readable:
        return None

    return sys.stdin.readline().strip()


def choose_track_from_matches(matches, last_id=None):
    candidates = matches

    if AVOID_IMMEDIATE_REPEAT and last_id is not None and len(matches) > 1:
        candidates = [t for t in matches if t["id"] != last_id]

    weights = [get_weight(t) for t in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


def find_requested_track(tracks, query, last_id=None):
    query = query.strip().casefold()
    if not query:
        return None, []

    def full_name(track):
        return f"{track['artist']} - {track['name']}"

    def reversed_full_name(track):
        return f"{track['name']} - {track['artist']}"

    exact_full_matches = [
        t for t in tracks
        if full_name(t).casefold() == query
        or reversed_full_name(t).casefold() == query
    ]
    if exact_full_matches:
        return choose_track_from_matches(exact_full_matches, last_id), exact_full_matches

    exact_name_matches = [
        t for t in tracks
        if t["name"].casefold() == query
    ]
    if exact_name_matches:
        version_separators = (" ", "-", "(", "[", "{", ":", "（", "［", "｛", "：")
        related_name_matches = []

        for track in tracks:
            name = track["name"].casefold()
            if name == query:
                related_name_matches.append(track)
                continue

            if name.startswith(query) and name[len(query):].startswith(version_separators):
                related_name_matches.append(track)

        return choose_track_from_matches(related_name_matches, last_id), related_name_matches

    exact_artist_matches = [
        t for t in tracks
        if t["artist"].casefold() == query
    ]
    if exact_artist_matches:
        return choose_track_from_matches(exact_artist_matches, last_id), exact_artist_matches

    partial_matches = [
        t for t in tracks
        if query in t["name"].casefold()
        or query in t["artist"].casefold()
        or query in full_name(t).casefold()
        or query in reversed_full_name(t).casefold()
    ]
    if partial_matches:
        return choose_track_from_matches(partial_matches, last_id), partial_matches

    return None, []


def normalize_command(command):
    return command.strip().casefold()


def parse_track_query(command):
    stripped = command.strip()

    if stripped.startswith(":"):
        return stripped[1:].strip()

    return None


def find_track_by_id(tracks, track_id):
    for track in tracks:
        if track["id"] == track_id:
            return track

    return None


def format_track(track):
    return f"{track['artist']} - {track['name']}"


def add_history(history, track):
    history.append({
        "id": track["id"],
        "name": track["name"],
        "artist": track["artist"],
    })

    if len(history) > HISTORY_LIMIT:
        del history[:-HISTORY_LIMIT]


def print_history(history):
    if not history:
        print("再生履歴はまだありません。")
        return

    print("直近の再生履歴:")
    for number, track in enumerate(reversed(history), start=1):
        print(f"  {number}. {format_track(track)}")


def print_track_choices(matches):
    print(f"{len(matches)}件の候補があります。番号を入力してください。")
    for number, track in enumerate(matches, start=1):
        print(f"  {number}. {format_track(track)}")
    print("  0. キャンセル")


def choose_track_by_number(matches, command):
    try:
        number = int(command.strip())
    except ValueError:
        return None, False

    if number == 0:
        return None, True

    if 1 <= number <= len(matches):
        return matches[number - 1], True

    return None, False


def print_help():
    print("操作:")
    print("  n                    次の曲へ")
    print("  p                    一時停止 / 再開")
    print("  stop                 再生停止")
    print("  current              再生中の曲を表示")
    print("  history              直近に再生した曲を表示")
    print("  reload               曲リストを更新")
    print("  :曲名                曲を指定")
    print("  :アーティスト - 曲名  曲を指定")
    print("  候補番号              複数候補から曲を選択")
    print("  Ctrl + C             終了")
    print("")
    print("起動時に曲リストを更新したいときは --reload を付けてください。")


def main():
    prepare_music()

    force_reload = any(arg in {"--reload", "--refresh", "-r"} for arg in sys.argv[1:])
    tracks = load_tracks(force_reload)

    if not tracks:
        print("プレイリストに曲がありません。")
        return

    print(f"{len(tracks)}曲を読み込みました。")
    print_help()

    last_id = None
    requested_track = None
    manually_stopped = False
    history = []

    while True:
        if requested_track is not None:
            picked = requested_track
            requested_track = None
        else:
            picked = pick_track(tracks, last_id)

        print(f"再生: {format_track(picked)}")

        play_track(picked)
        add_history(history, picked)
        last_id = picked["id"]
        last_position = None
        has_seen_current_track = False
        manually_stopped = False
        pending_matches = None

        while True:
            time.sleep(CHECK_INTERVAL)

            command = read_terminal_command()
            if command is not None:
                normalized_command = normalize_command(command)
                track_query = parse_track_query(command)

                if normalized_command in {"h", "help"}:
                    print_help()
                    continue

                if normalized_command in {"c", "cur", "current", "now"}:
                    print(f"再生中: {format_track(picked)}")
                    continue

                if normalized_command in {"history", "hist", "履歴"}:
                    print_history(history)
                    continue

                if normalized_command in {"reload", "refresh"}:
                    new_tracks = load_tracks(force_reload=True)
                    if not new_tracks:
                        print("曲リストが空だったため、更新を中止しました。")
                        continue

                    tracks = new_tracks
                    pending_matches = None
                    updated_picked = find_track_by_id(tracks, picked["id"])
                    if updated_picked is not None:
                        picked = updated_picked
                        last_id = picked["id"]
                    print(f"{len(tracks)}曲を読み込み直しました。")
                    continue

                if normalized_command in {"ㅜ", "n", "next", "次"}:
                    break

                if normalized_command in {"p", "pause", "一時停止"}:
                    manually_stopped = toggle_pause_or_resume(picked, manually_stopped)
                    continue

                if normalized_command in {"play", "resume", "r", "再生", "再開"}:
                    if manually_stopped:
                        play_track(picked)
                    else:
                        resume_music()
                    manually_stopped = False
                    print(f"再生再開: {format_track(picked)}")
                    continue

                if normalized_command in {"s", "stop", "停止", "ストップ"}:
                    stop_music()
                    manually_stopped = True
                    print("停止中。再開するには p または play を入力してください。")
                    continue

                if pending_matches is not None and track_query is None:
                    if normalized_command in {"cancel", "cxl", "キャンセル"}:
                        pending_matches = None
                        print("選択をキャンセルしました。")
                        continue

                    selected_track, handled = choose_track_by_number(pending_matches, command)

                    if not handled:
                        print("候補の番号を入力してください。キャンセルする場合は 0 を入力してください。")
                        continue

                    pending_matches = None

                    if selected_track is None:
                        print("選択をキャンセルしました。")
                        continue

                    requested_track = selected_track
                    print(f"次に指定: {format_track(requested_track)}")
                    break

                if track_query is None:
                    print(f"不明なコマンドです: {command}")
                    print("曲を指定する場合は :曲名 の形で入力してください。")
                    continue

                if not track_query:
                    print("曲名が空です。:曲名 の形で入力してください。")
                    continue

                requested_track, matches = find_requested_track(tracks, track_query, last_id)

                if requested_track is None:
                    print(f"曲が見つかりません: {track_query}")
                    continue

                if len(matches) > 1:
                    requested_track = None
                    pending_matches = matches
                    print_track_choices(matches)
                    continue

                print(f"次に指定: {format_track(requested_track)}")

                break

            status = get_player_status()

            if status["id"] == picked["id"]:
                has_seen_current_track = True

            # Musicアプリ側で別の曲に変わった場合
            if has_seen_current_track and status["id"] is not None and status["id"] != picked["id"]:
                break

            # 同じ曲の再生位置が先頭に戻った場合
            if last_position is not None:
                if status["id"] == picked["id"] and status["position"] + 2 < last_position:
                    break

            last_position = status["position"]

            if status["state"] == "paused":
                continue

            if status["state"] == "stopped":
                if manually_stopped:
                    continue
                break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n停止しました。")
