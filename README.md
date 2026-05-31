# Weighted Apple Music

Apple Musicの指定プレイリストから、重み付きで曲をランダム再生するPythonスクリプトです。

macOSのMusicアプリを`osascript`経由で操作します。

## Requirements

- macOS
- Apple Music / Music app
- Python 3
- Musicアプリを自動操作する権限

## Setup

`config.example.json`をコピーして`config.json`を作ります。

```bash
cp config.example.json config.json
```

`config.json`の`playlist_name`に再生したいプレイリスト名を設定します。

```json
{
  "playlist_name": "YOUR_PLAYLIST_NAME",
  "default_weight": 10,
  "artist_weights": {
    "Artist Name": 3
  },
  "track_weights": {
    "Track Name": 5
  },
  "avoid_immediate_repeat": true,
  "check_interval": 0.2
}
```

## Usage

```bash
python3 weighted_apple_music.py
```

初回起動時はMusicからプレイリストの曲情報を読み込み、`tracks_cache.json`に保存します。次回以降はキャッシュを使うので起動が速くなります。

プレイリストの内容を変更した場合は、キャッシュを更新してください。

```bash
python3 weighted_apple_music.py --reload
```

起動後に`reload`と入力しても更新できます。

## Commands

再生中のターミナルで以下を入力できます。

```text
n                    次の曲へ
p                    一時停止 / 再開
stop                 再生停止
current              再生中の曲を表示
history              直近に再生した曲を表示
reload               曲リストを更新
:曲名                曲を指定
:アーティスト - 曲名  曲を指定
候補番号              複数候補から曲を選択
Ctrl + C             終了
```

曲指定は `:` から始めます。

```text
:1000
:NCT WISH - 1000
:1000 - NCT WISH
```

複数候補がある場合は番号付きで表示されます。番号を入力するとその曲を次に再生します。
キャンセルする場合は `0` または `cancel` を入力してください。

## Weights

曲を選ぶときの重みは、次の順で決まります。

1. `track_weights`に曲名があれば、その値
2. `artist_weights`にアーティスト名があれば、その値
3. どちらもなければ`default_weight`

数字が大きいほど選ばれやすくなります。

## Notes

- 次の曲へ進む操作は、Musicアプリ側のボタンではなくターミナルの`n`コマンドで行います。
- プレイリスト名、曲名、アーティスト名はMusicアプリ内の表記と一致している必要があります。

## TODO

- `back`コマンドで直前の曲に戻れるようにする
- 再生中の曲の重みと、その重みが適用された理由を表示する
- READMEに実行例を追加する
