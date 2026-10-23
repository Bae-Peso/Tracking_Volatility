"""수집: 현지 시각이 fetch_hour 이후인 도시만 골라서 받는다 (cron 30분 간격)."""

import urllib.error
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import db
from .daily import day_rows
from .sources import openmeteo


def _now_local(city):
    return datetime.now(ZoneInfo(city["timezone"]))


def due_cities(conn, cities, fetch_hour):
    """현지 fetch_hour:00~23:59 사이이고, 오늘 fetch_hour 이후 수집분이 없는 도시."""
    due = []
    for city in cities:
        now = _now_local(city)
        if now.hour < fetch_hour:
            continue
        since = now.replace(hour=fetch_hour, minute=0, second=0, microsecond=0)
        since_utc = since.astimezone(timezone.utc).isoformat(timespec="seconds")
        if not db.fetched_since(conn, city["city_id"], now.date().isoformat(), since_utc, openmeteo.SOURCE):
            due.append(city)
    return due


def run(conn, cfg, force=False, city_ids=None):
    """받은 도시가 없으면 아무것도 출력하지 않는다 (30분마다 로그가 쌓이지 않게)."""
    cities = db.list_cities(conn, active_only=True)
    if city_ids:
        cities = [c for c in cities if c["city_id"] in city_ids]
    if not force:
        cities = due_cities(conn, cities, cfg["collect"]["fetch_hour"])
    if not cities:
        return

    nows = [_now_local(c) for c in cities]  # lead_days 기준 날짜는 요청 직전 현지 날짜
    try:
        results = openmeteo.fetch(cities, cfg["collect"]["forecast_days"])
    except (urllib.error.URLError, TimeoutError) as e:
        names = ", ".join(c["name"] for c in cities)
        raise SystemExit(f"{db.utc_now()} fetch failed ({names}): {e}")  # 다음 30분 실행이 재시도
    fetched_at = db.utc_now()
    for city, now, data in zip(cities, nows, results):
        slots = openmeteo.to_slots(data, city["city_id"], now.date(), fetched_at)
        days = day_rows(slots)
        db.upsert_weather(conn, slots + days)
        print(f"{now:%Y-%m-%d %H:%M %Z} saved {len(slots)}+{len(days)} rows for {city['name']}")
