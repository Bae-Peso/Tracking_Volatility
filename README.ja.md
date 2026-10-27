# 予報変動トラッカー (Tracking Volatility)

[한국어](README.md) | [English](README.en.md) | **日本語**

> **「14日前の天気予報はどこまで信じられるのか？」**
> 同じ日付の予報が14日前から当日までどう変わるかを毎日記録し、何日前の予報から信頼できるかを比較するセルフホスト型ツール。

> このツールの最初の企画と構造設計、DBスキーマ、天気の変化量などの数式のアイデアと表示項目など（プログラム全般）の設計は自分で行い、
> コードの作成には AI の支援を受けたことを明記します。

登録した都市の15日予報を毎日 **各都市の現地時刻22時** に [Open-Meteo](https://open-meteo.com/) から取得し、SQLite に蓄積します。
日付ごとに「n日前（1〜14）の予報が当日22時の予報とどれだけ違ったか」をスコアとして残し、
Web 画面で日別にそのまま見たり、週・月・年ごとに同じ n日前どうしで比較したりできます。

<img width="2306" height="1327" alt="{E17EC107-BAD0-4116-B4FC-33DE79E383C3}" src="https://github.com/user-attachments/assets/32da26bd-03be-4aa3-a4a9-5d7eeb0c3a5c" />


**上の画像はデータが蓄積される前の、以前のバージョンのものです。現在のバージョンとは画面構成が異なる場合があります。**

## 主な機能

- **収集**: 都市ごとに現地22時に15日予報（1時間単位）を取得し、1時間スロットと1日の集計値として保存。失敗した場合は30分後に再試行し、記録を残す
- **精度**: 日付 × n日前（1〜14）ごとに、当日の予報との差（気温・体感温度・降水確率・降水量・天気）と総合スコア。計算式に関しては[こちらのドキュメント](/docs/SCORING.jp.md)に整理している
- **Web 表示**（読み取り専用）
  - カレンダー: 週（当日 + 14個の n日前の値）、月（日付ごとに14マスの色帯）、年（その年の他の日と比べた色）
  - 日別表示: 14日前 → 当日の予報が当日とどれだけ違ったか（グラフ / 表）
  - グラフ: 1・2・4・8・16 分割、分割間のカーソル同期、最高・最低気温や体感温度の同時表示、点の単位は1時間〜1か月、ホイールで拡大・縮小、ドラッグで移動（最大2年）
  - 한국어 / English / 日本語、ライト・ダークモード、スマートフォン表示
- **セットアップ TUI**（韓・英・日）: 都市の検索・追加・登録解除、自動実行の登録
- **Docker Compose** で収集・Web・nginx をまとめて起動、再起動後も自動で再開

## 構成

```
                   毎 :00 / :30、現地22時を過ぎた都市のみ
  Open-Meteo API  ───────────────────────────────▶  collector (Python 標準ライブラリ)
                                                        │ 書き込み
  セットアップ TUI (curses) ── 都市の追加・解除 ───────▶ │
                                                        ▼
                                              data/weather.sqlite3
                                                        │ 読み取り専用
                                                        ▼
  ブラウザ  ◀── nginx :8080 ◀── web (Flask + gunicorn, /api/* JSON)
```

| 領域 | 技術 |
|---|---|
| 収集・精度計算 | Python 3.11+ **標準ライブラリのみ**（`urllib`, `sqlite3`, `zoneinfo`, `tomllib`, `curses`） |
| 保存 | SQLite（`city`, `weather`, `accuracy`, `error_log`） |
| Web | Flask + gunicorn、nginx、Chart.js 4.5（リポジトリに同梱）、バニラ JS、i18n JSON |
| 実行 | Docker Compose（collector · web · nginx）または cron |
| テスト | `unittest` 約70件（ネットワーク不要、1秒以内） |

## 設計で考えたこと

詳しい記録と変更理由（v1 → v8）は [PLAN.md](PLAN.md)（韓国語）にあります。

- **正解ではなく「当日22時の予報」を基準に** — 実測値を別に集めるのではなく、予報がどれだけ揺れたかに集中しました。当日夜の予報は、すでに過ぎた時間帯については実質的に実測に近いものです。
- **都市ごとに現地22時に収集** — 全都市を同じ時刻に取得すると、都市ごとに「当日の予報」の意味が変わってしまいます（ソウル22時 = ニューヨーク午前9時）。そこで30分ごとに起動し、現地22時を過ぎた都市だけを取得します。サマータイムは `zoneinfo` が処理します。
- **精度は「日付 × n日前」ごとに1行** — 最初は日付ごとにスコア1つ（範囲ベース）でしたが、n日前の情報が失われるうえ、収集が抜けた日は範囲が狭くなってスコアが良く出る偏りがありました。n日前ごとに保存したことで、「11月の7日前予報の精度」のような月別・年別の平均が自然に求まります。
- **スコアの項目は人が受ける影響ごとに** — 気温（暑さ・寒さ）、体感温度（湿度・風・日差し）、降水確率・降水量（濡れる）、天気（移動・安全）の5項目を0.2ずつ合計します。影響が重ならないように分け、同じ予報の外れを二重に減点しないようにしました。降水量は平方根スケールで比較し、0 → 1mm（傘が必要になる）を 10 → 11mm より大きく見つつ、10 → 20mm のような多い雨の側の差が小さくならないようにしました。
- **天気の重みはデータで決定** — 最初は天気コードごとに（種類, 強度）の座標を与えてその面積を使っていましたが、種類が違っても面積が同じだと差が0になりました。24都市・28日分の1時間予報でコードごとの視界・雪・路面凍結・突風を平均すると、霧雨・雨のコードは実質的に降水量の区分で、雨 ↔ 雪は気温で決まっていました。そこで天気の項目は降水量・気温では捉えられない移動・安全への影響（0〜1、霧 0.8、雷雨 0.75 …）だけを見るようにし、データのないコードと落雷の危険は判断で決めました（[`tools/weight_study.py`](tools/weight_study.py)、PLAN.md 5.1）。重みは臨時的に作成されたものであり、今後データの確保ができたら変更になる可能性もあります。
- **集計ルール** — グラフを3・6時間・1日単位でまとめるときは、最高気温は最大、最低気温は最小、降水量は合計。複数日をまとめるときは日最高気温の平均（平均最高気温）を使い、1時間ごとの気温を平均してしまうミスを避けました。
- **`city_id` は UUID** — 名前や座標を修正してもキーが変わらず、都市リストをエクスポートして別の DB に読み込んでも同じ都市として扱われます。
- **書き込みは1か所、Web は読み取り専用** — 書き込みは収集側だけにして SQLite の同時実行の問題を単純にしました。Web は `mode=ro` で開き、読み取り側でもファイル書き込みが必要な WAL の代わりに、標準のジャーナルモードとロック待ちを使っています。
- **収集側は標準ライブラリのみ** — 依存関係なしでどの Linux でも動くようにしました。Flask は Web 側だけで使います。
- **サーバーは文言ではなくコードを送る** — 天気は WMO コード、エラーはエラーコードで送り、翻訳は画面側の言語ファイルが行います。言語の追加は JSON ファイル1つで済み、足りないキーはテストが検出します。

## クイックスタート (Docker)

Docker Engine と compose プラグインが入った一般的な Linux PC があれば動きます（インストール: https://docs.docker.com/engine/install/）。

```bash
mkdir -p data                                          # 先に作成する（ないと Docker が root 所有で作成する）
printf 'UID=%s\nGID=%s\n' "$(id -u)" "$(id -g)" > .env  # UID/GID が 1000 なら省略可
docker compose run --rm collector setup                # セットアップ TUI: 言語 → 紹介 → 自動実行の案内 → 都市追加 → インストール
docker compose up -d --build                           # 収集 + Web を起動（再起動後も自動で再開）
docker compose logs -f collector                       # "serve: collect every 30 min" が表示されれば正常
```

Web 表示: `http://<この PC のアドレス>:8080`（ポートは `.env` の `WEB_PORT`）。読み取り専用で、ログインはありません。

<details>
<summary>Docker 設定の補足（sudo なしでの利用、UID/GID、ホストの cron からの移行）</summary>

- sudo なしで `docker` を使うには `sudo usermod -aG docker $USER` を実行して再ログインします。
  `docker` グループは実質的に root 権限なので、避けたい場合はコマンドごとに `sudo` を付けても構いません
  （[linux-postinstall](https://docs.docker.com/engine/install/linux-postinstall/)）。
- コンテナはホストのユーザーと同じ UID/GID で `data/` に書き込みます。デフォルトは 1000（多くのディストリビューションで最初に作成されるアカウント）。
  シェルの `$UID` は Docker に渡されず、`sudo` を付けると環境変数がリセットされるため、`.env` ファイルで渡します。`.env` は git に含めません。
- その他のコマンドは `docker compose run --rm collector <コマンド>`（下の「コマンド」の `python3 -m accu_weather` の代わりに）。
- ホストの cron で動かしていた場合は、先に `./run.sh uninstall` を実行します（PLAN.md 7.6）。

</details>

## Docker を使わない場合

Python 3.11+ と cron、`flock`、`timeout`（Linux 標準）があれば動きます。

```bash
python3 -m accu_weather setup      # セットアップ TUI。最後の「インストール」で都市を登録し、crontab に30分間隔で登録
```

Web は別に起動します: `pip install -r web/requirements.txt` のあと `flask --app web.app run`。

## コマンド

```bash
python3 -m accu_weather setup                                       # セットアップ TUI（再実行すると登録解除も可能）
python3 -m accu_weather city add "Osaka"                            # 英語名で検索して追加
python3 -m accu_weather city add "Seoul" --lat 37.57 --lon 126.98   # 座標で追加（タイムゾーンは自動）
python3 -m accu_weather city list [--all]
python3 -m accu_weather city disable <id> [--purge]                 # 収集を停止 / --purge: データも削除
python3 -m accu_weather city enable <id>
python3 -m accu_weather city export | import [path]                 # 都市リスト ↔ cities.txt（city_id を含む）

python3 -m accu_weather collect [--force] [--city <id>]             # 手動で収集（--force: 時刻を無視）
python3 -m accu_weather serve                                       # 常駐実行: 毎 :00/:30 に collect（Docker のデフォルト）
python3 -m accu_weather recompute [--city <id>]                     # 精度をすべて再計算（config 変更後）

./run.sh install | uninstall                                        # crontab の登録 / 解除（Docker を使わない場合）
```

`<id>` は `city list` に表示される UUID の先頭8文字だけでも指定できます。

## Web 画面

| モード | 表示内容 |
|---|---|
| カレンダー · 週 | 7日 × （当日 + 1日前〜14日前）、選んだ項目の値と色 |
| カレンダー · 月 | 通常のカレンダー。各マスに当日の天気・気温と14マスの帯（1日前 → 14日前）、緑（変動が少ない）→ 赤（多い） |
| カレンダー · 年 | 画面の比率に合わせて 4×3 / 3×4 / 6×2 …、小さすぎる場合はスクロール。日付ごとの変動の中央値を、その年の他の日付と比べた色 |
| 日別（日付をクリック） | 14日前 → 当日の予報が当日とどれだけ違ったか、グラフ / 表 |
| グラフ | 分割ごとに都市・項目を選択、n日前ごとの予報の線。点の単位は1時間〜1か月（最高は最大・最低は最小、複数日なら平均最高・最低、降水量は合計） |

収集に失敗すると上部に ⚠ の通知が表示されます（「確認」はそのブラウザにだけ保存され、DB の記録はそのまま）。
言語の追加は `web/static/i18n/` に JSON ファイル1つ + `weather_code.json` に天気名を追加するだけです（PLAN.md 7.5）。

## プロジェクト構成

```
accu_weather/        収集側（標準ライブラリのみ）: collect, scheduler(serve), accuracy, db, setup TUI
  sources/openmeteo.py   Open-Meteo へのリクエスト、1時間値 → 1時間スロットの行
web/                 Web 表示: app.py(Flask), queries.py(データ), templates/, static/(app.js, i18n/, vendor/)
tests/               unittest（収集・精度・スケジューラ・TUI・Web・i18n ファイル）
config.toml          収集時刻・期間、精度の重み・基準値
weather_code.json    WMO 天気コード → カテゴリ、名前(ko/en/ja)
weather_weight.json  WMO 天気コード → 重み 0〜1（移動・安全への影響）
tools/weight_study.py  重みを決めるときに使った分析（複数都市のデータ → コードごとの影響）
Dockerfile, web/Dockerfile, compose.yaml, run.sh
PLAN.md              設計記録（v1 〜 v8、決定事項。韓国語）
```

## テスト

```bash
python3 -m unittest        # ネットワーク不要、1秒以内（Flask がない場合は Web エンドポイントのテストをスキップ）
```

## データを直接見る

```bash
sqlite3 -readonly -box data/weather.sqlite3 \
  "SELECT target_date, lead_days, weather, temp_max, temp_min, precip_mm, precip_prob
   FROM weather JOIN city USING (city_id)
   WHERE city.name = 'Osaka' AND slot = 'day' ORDER BY target_date, lead_days DESC"
```

月別・週別の n日前精度のクエリは [PLAN.md 5.2](PLAN.md) を参照してください。

## データの出典

- 気象データ: [Weather data by Open-Meteo.com](https://open-meteo.com/)（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)）。Web 画面の上部にも出典リンクを表示しています。
- グラフ: [Chart.js](https://www.chartjs.org/) 4.5.1（MIT、`web/static/vendor/` にライセンスを同梱）

## ライセンス

[MIT](LICENSE) © 2026 Bae_Peso
