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

-- 날짜 하나에 n일전(1~14)마다 한 줄: "n일 전 예보가 d0(당일 22시 예보)와 얼마나 같았나"
CREATE TABLE IF NOT EXISTS accuracy (
  target_date      TEXT    NOT NULL,      -- 대상 날짜 (도시 현지)
  city_id          TEXT    NOT NULL REFERENCES city(city_id),
  lead_days        INTEGER NOT NULL,      -- 1~14
  source           TEXT    NOT NULL DEFAULT 'open-meteo',
  weather_match    INTEGER,               -- 날씨 카테고리가 d0와 같으면 1, 다르면 0
  weather_severity REAL,                  -- |w − w(d0)| / 5, 0~1
  temp_max_diff    REAL,                  -- n일전 − d0 ℃ (+면 높게 예보)
  temp_min_diff    REAL,
  precip_prob_diff INTEGER,               -- n일전 − d0 %p
  precip_log_diff  REAL,                  -- log1p(n일전 mm) − log1p(d0 mm)
  score            REAL,                  -- 0~100, 높을수록 d0와 가까움
  computed_at      TEXT    NOT NULL,
  PRIMARY KEY (city_id, target_date, lead_days, source)
);

-- 수집 실패 기록. 웹에서 확인하면 read_at을 채워 알림에서 뺀다 (기록은 남김).
CREATE TABLE IF NOT EXISTS error_log (
  error_id    INTEGER PRIMARY KEY,
  occurred_at TEXT NOT NULL,             -- UTC
  message     TEXT NOT NULL,
  read_at     TEXT                       -- NULL이면 아직 확인 안 함
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
    _upsert(conn, "weather", ["city_id", "target_date", "slot", "lead_days", "source"], rows)


def fetched_since(conn, city_id, local_date, since_utc, source):
    """local_date의 당일(d0) 예보를 since_utc 이후에 받은 적이 있으면 True."""
    row = conn.execute(
        "SELECT 1 FROM weather WHERE city_id = ? AND target_date = ? AND lead_days = 0 "
        "AND source = ? AND fetched_at >= ? LIMIT 1",
        (city_id, local_date, source, since_utc),
    ).fetchone()
    return row is not None


def _upsert(conn, table, key_cols, rows):
    if not rows:
        return
    cols = list(rows[0])
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in key_cols)
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) "
        f"VALUES ({', '.join(':' + c for c in cols)}) "
        f"ON CONFLICT ({', '.join(key_cols)}) DO UPDATE SET {updates}"
    )
    with conn:
        conn.executemany(sql, rows)


def day_forecasts(conn, city_id, target_date, source):
    """한 날짜의 하루 통합 예보 전부 (lead_days 오름차순)."""
    return conn.execute(
        "SELECT * FROM weather WHERE city_id = ? AND target_date = ? AND slot = 'day' AND source = ? "
        "ORDER BY lead_days",
        (city_id, target_date, source),
    ).fetchall()


def d0_dates(conn, city_id=None):
    """d0(당일 예보)가 있는 (city_id, target_date, source) 목록. recompute 대상."""
    sql = "SELECT city_id, target_date, source FROM weather WHERE slot = 'day' AND lead_days = 0"
    params = ()
    if city_id:
        sql += " AND city_id = ?"
        params = (city_id,)
    return conn.execute(sql + " ORDER BY target_date", params).fetchall()


# ---- accuracy ----

def upsert_accuracy(conn, rows):
    _upsert(conn, "accuracy", ["city_id", "target_date", "lead_days", "source"], rows)


# ---- error_log ----

def log_error(conn, message):
    with conn:
        conn.execute("INSERT INTO error_log (occurred_at, message) VALUES (?, ?)", (utc_now(), message))
