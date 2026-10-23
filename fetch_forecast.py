#!/usr/bin/env python3
"""Open-Meteo 예보를 받아 3시간 슬롯으로 묶어 SQLite에 저장한다 (도시 1곳, 수동 지정).

cron으로 매일 22:00, 23:00, 23:30 세 번 실행한다. 오늘 22시 이후에 이미 받았으면
나머지 실행은 건너뛴다 (앞 실행이 실패했을 때만 뒤 실행이 실제로 받는다).

사용법:
    python3 fetch_forecast.py          # 받아와서 저장 (오늘 22시 이후 수집분이 있으면 건너뜀)
    python3 fetch_forecast.py --force  # 건너뛰기 없이 받아와서 저장
    python3 fetch_forecast.py --show   # 저장된 내용 출력만
"""

import json
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# ---- 수동 지정 도시 ----
CITY = "osaka"
LATITUDE = 34.70
LONGITUDE = 135.50
TIMEZONE = "Asia/Tokyo"  # 날짜·lead_days·22시 판단 기준

FETCH_FROM_HOUR = 22  # 이 시각 이후 수집분을 그날의 확정 예보로 본다
FORECAST_DAYS = 15  # 오늘 + 14일
SLOT_HOURS = 3
SOURCE = "open-meteo"
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "weather.sqlite3"

# WMO 코드 → {category, en, ko, ja} / {x, y}
WEATHER_CODES = json.loads((BASE_DIR / "weather_code.json").read_text(encoding="utf-8"))
SEVERITY_XY = json.loads((BASE_DIR / "weather_severity.json").read_text(encoding="utf-8"))

API_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARS = [
    "weather_code",
    "temperature_2m",
    "wind_speed_10m",
    "visibility",
    "precipitation",
    "precipitation_probability",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS weather (
  target_date  TEXT    NOT NULL,      -- 날짜 '2026-10-24'
  slot         TEXT    NOT NULL,      -- '00','03',…,'21'
  city         TEXT    NOT NULL,      -- 도시
  lead_days    INTEGER NOT NULL,      -- n일전 예보 (0~14)
  weather      INTEGER,               -- 날씨 카테고리 1~6
  weather_code INTEGER,               -- WMO 원본 코드
  temp_max     REAL,                  -- 최고 기온 ℃
  temp_min     REAL,                  -- 최저 기온 ℃
  wind_kmh     REAL,                  -- 바람 km/h
  visibility_m REAL,                  -- 가시거리 m
  precip_mm    REAL,                  -- 강수량 mm
  precip_prob  INTEGER,               -- 강수확률 %
  source       TEXT    NOT NULL,
  fetched_at   TEXT    NOT NULL,
  PRIMARY KEY (city, target_date, slot, lead_days, source)
);
"""


def weather_category(code):
    """WMO 코드 → 1 맑음, 2 구름/흐림, 3 안개, 4 비, 5 눈, 6 뇌우 (weather_code.json)."""
    entry = WEATHER_CODES.get(str(code))
    return entry["category"] if entry else None


def weather_weight(code):
    """WMO 코드 → 가중치 0~5 (원점~(x,y) 넓이, weather_severity.json). 모르는 코드는 0."""
    xy = SEVERITY_XY.get(str(code))
    return xy["x"] * xy["y"] / 15 * 5 if xy else 0.0


def fetch():
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": ",".join(HOURLY_VARS),
        "timezone": TIMEZONE,
        "forecast_days": FORECAST_DAYS,
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "accu_weather/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _values(xs):
    return [x for x in xs if x is not None]


def to_slots(data, fetched_at):
    """1시간 값을 3시간 슬롯 행으로 묶는다."""
    hourly = data["hourly"]
    today = fetched_at.date()
    rows = []
    for i in range(0, len(hourly["time"]), SLOT_HOURS):
        start = datetime.fromisoformat(hourly["time"][i])
        chunk = {var: hourly[var][i : i + SLOT_HOURS] for var in HOURLY_VARS}

        codes = _values(chunk["weather_code"])
        temps = _values(chunk["temperature_2m"])
        winds = _values(chunk["wind_speed_10m"])
        vis = _values(chunk["visibility"])
        precip = _values(chunk["precipitation"])
        prob = _values(chunk["precipitation_probability"])

        # 가중치가 가장 큰 코드가 대표 날씨 (같으면 코드 번호가 큰 쪽)
        code = max(codes, key=lambda c: (weather_weight(c), c)) if codes else None
        target = start.date()
        rows.append({
            "target_date": target.isoformat(),
            "slot": f"{start.hour:02d}",
            "city": CITY,
            "lead_days": (target - today).days,
            "weather": weather_category(code),
            "weather_code": code,
            "temp_max": max(temps) if temps else None,
            "temp_min": min(temps) if temps else None,
            "wind_kmh": max(winds) if winds else None,
            "visibility_m": min(vis) if vis else None,
            "precip_mm": round(sum(precip), 2) if precip else None,
            "precip_prob": max(prob) if prob else None,
            "source": SOURCE,
            "fetched_at": fetched_at.isoformat(timespec="seconds"),
        })
    return rows


def save(conn, rows):
    cols = list(rows[0])
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols)
    sql = (
        f"INSERT INTO weather ({', '.join(cols)}) "
        f"VALUES ({', '.join(':' + c for c in cols)}) "
        f"ON CONFLICT (city, target_date, slot, lead_days, source) DO UPDATE SET {updates}"
    )
    with conn:
        conn.executemany(sql, rows)


def already_fetched(conn, now):
    """오늘 FETCH_FROM_HOUR시 이후에 이미 받은 적이 있으면 True."""
    since = now.replace(hour=FETCH_FROM_HOUR, minute=0, second=0, microsecond=0)
    if now < since:
        return False
    row = conn.execute(
        "SELECT 1 FROM weather WHERE city = ? AND source = ? AND fetched_at >= ? LIMIT 1",
        (CITY, SOURCE, since.isoformat(timespec="seconds")),
    ).fetchone()
    return row is not None


def show(conn):
    cur = conn.execute(
        "SELECT target_date, slot, city, lead_days, weather, weather_code, temp_max, temp_min, "
        "wind_kmh, visibility_m, precip_mm, precip_prob, fetched_at "
        "FROM weather ORDER BY target_date, slot, lead_days"
    )
    header = [d[0] for d in cur.description]
    print(" | ".join(header))
    for row in cur:
        print(" | ".join("" if v is None else str(v) for v in row))
    total = conn.execute("SELECT COUNT(*) FROM weather").fetchone()[0]
    print(f"-- {total} rows in {DB_PATH}")


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    if "--show" in sys.argv:
        show(conn)
    else:
        now = datetime.now(ZoneInfo(TIMEZONE))
        if "--force" not in sys.argv and already_fetched(conn, now):
            print(f"{now:%Y-%m-%d %H:%M} skip: {CITY} already fetched after {FETCH_FROM_HOUR}:00 today")
        else:
            data = fetch()
            fetched_at = datetime.now(ZoneInfo(TIMEZONE))
            rows = to_slots(data, fetched_at)
            save(conn, rows)
            print(f"{fetched_at:%Y-%m-%d %H:%M} saved {len(rows)} rows for {CITY}")
    conn.close()


if __name__ == "__main__":
    main()
