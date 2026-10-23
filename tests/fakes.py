"""테스트용 가짜 Open-Meteo 응답, 임시 DB, 가짜 시계."""

import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from accu_weather import config, db


def hourly_data(start, days, code=0, temp=10.0, wind=5.0, vis=20000.0, precip=0.0, prob=0, feel=None):
    """start(date)부터 days일치, 모든 시각이 같은 값인 1시간 단위 응답. 테스트에서 리스트를 직접 고쳐 쓴다.
    체감온도(feel)를 안 주면 기온과 같다."""
    times = [f"{start + timedelta(days=d)}T{h:02d}:00" for d in range(days) for h in range(24)]
    n = len(times)
    return {"hourly": {
        "time": times,
        "weather_code": [code] * n,
        "temperature_2m": [temp] * n,
        "apparent_temperature": [temp if feel is None else feel] * n,
        "wind_speed_10m": [wind] * n,
        "visibility": [vis] * n,
        "precipitation": [precip] * n,
        "precipitation_probability": [prob] * n,
    }}


def local(tz, *args):
    """local("Asia/Tokyo", 2026, 10, 23, 22, 0) → 그 도시 현지 시각."""
    return datetime(*args, tzinfo=ZoneInfo(tz))


class TempDB:
    """with TempDB() as conn: … 임시 파일 DB (테스트가 끝나면 지워짐)."""

    def __enter__(self):
        self._dir = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self._dir.name) / "test.sqlite3")
        return self.conn

    def __exit__(self, *exc):
        self.conn.close()
        self._dir.cleanup()


def add_osaka(conn):
    return db.add_city(conn, "Osaka", "Japan", 34.69, 135.50, "Asia/Tokyo")


def cfg():
    return config.load()


TODAY = date(2026, 10, 23)
