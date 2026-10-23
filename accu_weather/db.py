"""SQLite 스키마, 도시 관리, weather upsert."""

import sqlite3
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS city (
  city_id    TEXT PRIMARY KEY,        -- uuid4
  name       TEXT NOT NULL,           -- 'Osaka' (영어)
  country    TEXT,                    -- 'Japan' (영어)
  latitude   REAL NOT NULL,           -- 소수 둘째 자리로 반올림
  longitude  REAL NOT NULL,
  timezone   TEXT NOT NULL,           -- 'Asia/Tokyo' (현지 22시 확정 기준)
  active     INTEGER NOT NULL DEFAULT 1,
  added_at   TEXT NOT NULL,
  UNIQUE (latitude, longitude)
);

CREATE TABLE IF NOT EXISTS weather (
  target_date  TEXT    NOT NULL,      -- 날짜 '2026-10-24' (도시 현지)
  slot         TEXT    NOT NULL,      -- '00','03',…,'21' 또는 'day'(하루 통합)
  city_id      TEXT    NOT NULL REFERENCES city(city_id),
  lead_days    INTEGER NOT NULL,      -- n일전 예보 (0~14)
  weather      INTEGER,               -- 날씨 카테고리 1~6
  weather_code INTEGER,               -- WMO 원본 코드
  temp_max     REAL,                  -- 최고 기온 ℃
  temp_min     REAL,                  -- 최저 기온 ℃
  wind_kmh     REAL,                  -- 바람 km/h
  visibility_m REAL,                  -- 가시거리 m
  precip_mm    REAL,                  -- 강수량 mm
  precip_prob  INTEGER,               -- 강수확률 %
  source       TEXT    NOT NULL DEFAULT 'open-meteo',
  fetched_at   TEXT    NOT NULL,      -- 수집 시각 (UTC)
  PRIMARY KEY (city_id, target_date, slot, lead_days, source)
);
CREATE INDEX IF NOT EXISTS idx_weather_date ON weather (target_date, slot);

CREATE TABLE IF NOT EXISTS accuracy (
  target_date         TEXT    NOT NULL,
  city_id             TEXT    NOT NULL REFERENCES city(city_id),
  source              TEXT    NOT NULL DEFAULT 'open-meteo',
  n_forecasts         INTEGER,          -- 3~15 (3개 미만이면 행 없음)
  ref_lead            INTEGER,          -- 기준 예보의 lead_days (보통 0)
  temp_max_dev        REAL,             -- 기준 예보와의 차이 평균
  temp_min_dev        REAL,
  precip_prob_dev     REAL,
  precip_log_dev      REAL,
  weather_severity    REAL,
  weather_changes     INTEGER,
  weather_change_rate REAL,
  stability_score     REAL,
  computed_at         TEXT    NOT NULL,
  PRIMARY KEY (city_id, target_date, source)
);
"""

CITY_COLS = ["city_id", "name", "country", "latitude", "longitude", "timezone", "active", "added_at"]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(weather)")]
    if "city" in cols:
        raise SystemExit(f"{path}: 프로토타입(city TEXT) 스키마입니다. 파일을 옮기거나 지운 뒤 다시 실행하세요.")
    conn.executescript(SCHEMA)
    return conn


# ---- city ----

def add_city(conn, name, country, latitude, longitude, tz, city_id=None, active=1, added_at=None):
    city_id = city_id or str(uuid.uuid4())
    with conn:
        conn.execute(
            f"INSERT INTO city ({', '.join(CITY_COLS)}) VALUES ({', '.join('?' * len(CITY_COLS))})",
            (city_id, name, country, round(latitude, 2), round(longitude, 2), tz, active, added_at or utc_now()),
        )
    return city_id


def list_cities(conn, active_only=False):
    sql = "SELECT * FROM city" + (" WHERE active = 1" if active_only else "") + " ORDER BY added_at"
    return conn.execute(sql).fetchall()


def find_city(conn, prefix):
    """city_id 앞부분(8자 정도)만으로 찾는다. 없거나 여러 개면 SystemExit."""
    rows = conn.execute("SELECT * FROM city WHERE city_id LIKE ? || '%'", (prefix,)).fetchall()
    if len(rows) != 1:
        raise SystemExit(f"'{prefix}': " + ("해당 도시 없음" if not rows else f"{len(rows)}개가 일치함, 더 길게 입력"))
    return rows[0]


def set_active(conn, city_id, active):
    with conn:
        conn.execute("UPDATE city SET active = ? WHERE city_id = ?", (int(active), city_id))


def purge_city(conn, city_id):
    with conn:
        for table in ("weather", "accuracy", "city"):
            conn.execute(f"DELETE FROM {table} WHERE city_id = ?", (city_id,))


# ---- weather ----

def upsert_weather(conn, rows):
    if not rows:
        return
    cols = list(rows[0])
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols)
    sql = (
        f"INSERT INTO weather ({', '.join(cols)}) "
        f"VALUES ({', '.join(':' + c for c in cols)}) "
        f"ON CONFLICT (city_id, target_date, slot, lead_days, source) DO UPDATE SET {updates}"
    )
    with conn:
        conn.executemany(sql, rows)


def fetched_since(conn, city_id, local_date, since_utc, source):
    """local_date의 당일(d0) 예보를 since_utc 이후에 받은 적이 있으면 True."""
    row = conn.execute(
        "SELECT 1 FROM weather WHERE city_id = ? AND target_date = ? AND lead_days = 0 "
        "AND source = ? AND fetched_at >= ? LIMIT 1",
        (city_id, local_date, source, since_utc),
    ).fetchone()
    return row is not None
