# Tracking Volatility

[한국어](README.md) | **English** | [日本語](README.ja.md)

> **"How much can you trust a 14-day weather forecast?"**
> A self-hosted tool that records every day how the forecast for the same date changes from 14 days out to the day itself, and compares how many days ahead a forecast becomes reliable.

> I did the initial planning, the architecture, the DB Schema, the formula ideas such as how weather change is measured, and the choice of what to display (the overall design of the program) myself,
> and wrote the code with the help of AI.

Every day at **22:00 local time in each city**, it fetches a 15-day forecast for each registered city from [Open-Meteo](https://open-meteo.com/) and stores it in SQLite.
For each date it scores "how far the n-days-before forecast (1–14) was from that day's 22:00 forecast",
and the web viewer shows the daily results as they are, or compares the same lead across weeks, months and years.

<img width="2364" height="1393" alt="Web viewer screenshot" src="https://github.com/user-attachments/assets/10a2e63a-a5e6-46e0-85fd-e5164954eea7" />

**This screenshot was taken before data had accumulated and on an earlier version, so the layout may differ from the current version.**

## Features

- **Collection**: fetches each city's 15-day forecast (hourly) at local 22:00 and stores it as hourly slots plus a daily summary. On failure it retries 30 minutes later and logs the error
- **Accuracy**: for each date × lead (1–14 days before), the difference from the same-day forecast (temperature, feels-like temperature, precipitation probability, precipitation, weather) and an overall score. About scoring, I organized the document at [here](/docs/SCORING.en.md).
- **Web viewer** (read-only)
  - Calendar: week (same day + 14 lead values), month (a 14-cell color strip per date), year (color relative to the other days of that year)
  - Day view: how far each forecast from 14 days before → the day itself was from the same-day forecast (chart / table)
  - Graphs: 1·2·4·8·16 split panels, synced cursor across panels, high and low temperature or feels-like temperature together, point step from 1 hour to 1 month, wheel zoom and drag to pan (up to 2 years)
  - 한국어 / English / 日本語, light and dark themes, phone layout
- **Setup TUI** (Korean, English, Japanese): search, add and unregister cities, register automatic runs
- **Docker Compose** runs the collector, web and nginx together and restarts them after a reboot

## Architecture

```
                   every :00 / :30, only cities past local 22:00
  Open-Meteo API  ───────────────────────────────▶  collector (Python stdlib)
                                                        │ write
  Setup TUI (curses) ── add / remove cities ──────────▶ │
                                                        ▼
                                              data/weather.sqlite3
                                                        │ read-only
                                                        ▼
  Browser  ◀── nginx :8080 ◀── web (Flask + gunicorn, /api/* JSON)
```

| Area | Technology |
|---|---|
| Collection and accuracy | Python 3.11+ **standard library only** (`urllib`, `sqlite3`, `zoneinfo`, `tomllib`, `curses`) |
| Storage | SQLite (`city`, `weather`, `accuracy`, `error_log`) |
| Web | Flask + gunicorn, nginx, Chart.js 4.5 (vendored), vanilla JS, i18n JSON |
| Runtime | Docker Compose (collector · web · nginx) or cron |
| Tests | ~70 `unittest` tests (no network, under 1 second) |

## Design decisions

The full record and the reasons behind each change (v1 → v8) are in [PLAN.md](PLAN.md) (Korean).

- **The same-day 22:00 forecast as the reference instead of ground truth** — rather than collecting observations separately, the project focuses on how much the forecast wavered. For hours that have already passed, the forecast issued that night is effectively an observation.
- **Collect at 22:00 local time per city** — fetching every city at one moment would give "same-day forecast" a different meaning per city (22:00 in Seoul is 09:00 in New York). So the collector wakes every 30 minutes and fetches only the cities that have passed local 22:00. Daylight saving time is handled by `zoneinfo`.
- **Accuracy stored as one row per date × lead** — the first design had one range-based score per date, but it lost the lead information and was biased: days with missed collections had a narrower range and scored better. Storing each lead separately makes monthly and yearly averages such as "accuracy of 7-day-ahead forecasts in November" fall out naturally.
- **Score items split by how they affect people** — temperature (heat and cold), feels-like temperature (humidity, wind and sun), precipitation probability and amount (getting wet) and weather (travel and safety) are combined at 0.2 each. They are split so that their effects do not overlap and the same forecast miss is not penalized twice. Precipitation is compared on a square-root scale so that 0 → 1 mm (now you need an umbrella) counts for more than 10 → 11 mm, while differences in heavy rain such as 10 → 20 mm do not shrink.
- **Weather weights chosen from data** — the first version gave each weather code (kind, intensity) coordinates and used their area, but codes of different kinds with the same area came out as no change. Averaging visibility, snow, ice and gusts per code over 28 days of hourly forecasts for 24 cities showed that the drizzle and rain codes are effectively precipitation bands, and that rain vs snow is decided by temperature. So the weather item only measures the impact on travel and safety that precipitation and temperature miss (0–1, fog 0.8, thunderstorm 0.75 …), and codes without data and lightning risk were set by judgment ([`tools/weight_study.py`](tools/weight_study.py), PLAN.md 5.1). Also, Those weights are temporary numbers that has a chance to change at future.
- **Aggregation rules** — when graphs group points into 3 hours, 6 hours or a day, the high is the maximum, the low is the minimum and precipitation is the sum. When grouping several days, it takes the mean of the daily highs (average high), avoiding the mistake of averaging hourly temperatures.
- **`city_id` is a UUID** — the key survives renaming a city or correcting its coordinates, and a city exported from one DB and imported into another stays the same city.
- **One writer, read-only web** — only the collector writes, which keeps SQLite concurrency simple. The web opens the DB with `mode=ro`, and since WAL would require the reader to write files too, it uses the default journal mode with a busy timeout.
- **Collector uses the standard library only** — no dependencies, so it runs on any Linux. Flask is used only on the web side.
- **The server sends codes, not text** — weather is sent as WMO codes and errors as error codes, and the language files in the browser translate them. Adding a language takes one JSON file, and tests catch missing keys.

## Quick start (Docker)

Any ordinary Linux PC with Docker Engine and the compose plugin will do (install: https://docs.docker.com/engine/install/).

```bash
mkdir -p data                                          # create it first (otherwise Docker creates it owned by root)
printf 'UID=%s\nGID=%s\n' "$(id -u)" "$(id -g)" > .env  # can be skipped if your UID/GID is 1000
docker compose run --rm collector setup                # setup TUI: language → intro → auto-run notice → add cities → install
docker compose up -d --build                           # start collection + web (restarts after reboot)
docker compose logs -f collector                       # "serve: collect every 30 min" means it is running
```

Web viewer: `http://<this PC's address>:8080` (port set by `WEB_PORT` in `.env`). It is read-only and has no login.

<details>
<summary>Docker notes (running without sudo, UID/GID, moving from host cron)</summary>

- To use `docker` without sudo, run `sudo usermod -aG docker $USER` and log in again.
  The `docker` group is effectively root, so if you would rather not, prefix each command with `sudo` instead
  ([linux-postinstall](https://docs.docker.com/engine/install/linux-postinstall/)).
- The container writes to `data/` with the same UID/GID as the host user. The default is 1000 (the first account created on most distributions).
  The shell's `$UID` is not passed to Docker and `sudo` resets environment variables, so the values go through the `.env` file. `.env` is not committed to git.
- For other commands, use `docker compose run --rm collector <command>` (in place of `python3 -m accu_weather` under "Commands" below).
- If you were running it from host cron, run `./run.sh uninstall` first (PLAN.md 7.6).

</details>

## Without Docker

You need Python 3.11+, cron, `flock` and `timeout` (standard on Linux).

```bash
python3 -m accu_weather setup      # setup TUI. The final "Install" step registers the cities and adds a 30-minute crontab entry
```

Run the web viewer separately: `pip install -r web/requirements.txt`, then `flask --app web.app run`.

## Commands

```bash
python3 -m accu_weather setup                                       # setup TUI (run again to unregister cities)
python3 -m accu_weather city add "Osaka"                            # search by English name and add
python3 -m accu_weather city add "Seoul" --lat 37.57 --lon 126.98   # add by coordinates (time zone detected)
python3 -m accu_weather city list [--all]
python3 -m accu_weather city disable <id> [--purge]                 # stop collecting / --purge: delete its data too
python3 -m accu_weather city enable <id>
python3 -m accu_weather city export | import [path]                 # city list ↔ cities.txt (includes city_id)

python3 -m accu_weather collect [--force] [--city <id>]             # collect manually (--force: ignore the time)
python3 -m accu_weather serve                                       # long-running: collect at every :00/:30 (Docker default)
python3 -m accu_weather recompute [--city <id>]                     # recompute all accuracy (after changing config)

./run.sh install | uninstall                                        # add / remove the crontab entry (without Docker)
```

For `<id>`, the first 8 characters of the UUID shown by `city list` are enough.

## Web viewer

| Mode | What it shows |
|---|---|
| Calendar · week | 7 days × (same day + 1 to 14 days before), value and color of the chosen metric |
| Calendar · month | A regular calendar. Each cell shows the day's weather and temperatures and a 14-cell strip (1 → 14 days before), green (little change) → red (a lot) |
| Calendar · year | Fits the screen as 4×3 / 3×4 / 6×2 …, scrolls if too small. Each date is colored by its median change relative to the other dates of that year |
| Day (click a date) | How far each forecast from 14 days before → the day itself was from the same-day forecast, chart / table |
| Graphs | City and metric per panel, one line per lead. Point step from 1 hour to 1 month (high = max, low = min, average high/low across several days, precipitation summed) |

If collection fails, a ⚠ alert appears at the top ("OK" is remembered only in that browser; the DB record stays).
Adding a language takes one JSON file in `web/static/i18n/` plus weather names in `weather_code.json` (PLAN.md 7.5).

## Project structure

```
accu_weather/        collector (stdlib only): collect, scheduler (serve), accuracy, db, setup TUI
  sources/openmeteo.py   Open-Meteo requests, hourly values → hourly slot rows
web/                 web viewer: app.py (Flask), queries.py (data), templates/, static/ (app.js, i18n/, vendor/)
tests/               unittest (collection, accuracy, scheduler, TUI, web, i18n files)
config.toml          collection time and range, accuracy weights and thresholds
weather_code.json    WMO weather code → category, names (ko/en/ja)
weather_weight.json  WMO weather code → weight 0–1 (impact on travel and safety)
tools/weight_study.py  analysis used to choose the weights (data from many cities → impact per code)
Dockerfile, web/Dockerfile, compose.yaml, run.sh
PLAN.md              design record (v1 – v8, decisions; Korean)
```

## Tests

```bash
python3 -m unittest        # no network, under 1 second (web endpoint tests are skipped without Flask)
```

## Querying the data directly

```bash
sqlite3 -readonly -box data/weather.sqlite3 \
  "SELECT target_date, lead_days, weather, temp_max, temp_min, precip_mm, precip_prob
   FROM weather JOIN city USING (city_id)
   WHERE city.name = 'Osaka' AND slot = 'day' ORDER BY target_date, lead_days DESC"
```

For monthly and weekly per-lead accuracy queries, see [PLAN.md 5.2](PLAN.md).

## Data sources

- Weather data: [Weather data by Open-Meteo.com](https://open-meteo.com/) ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)). The web viewer also shows the attribution link at the top.
- Charts: [Chart.js](https://www.chartjs.org/) 4.5.1 (MIT, license included in `web/static/vendor/`)

## License

[MIT](LICENSE) © 2026 Bae_Peso
