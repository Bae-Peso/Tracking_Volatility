"""Open-Meteo 예보 요청 + 1시간 값을 슬롯 행으로 바꾸기, 도시 검색."""

import json
import urllib.parse
import urllib.request
from datetime import datetime

from .. import codes

SOURCE = "open-meteo"
SLOT_HOURS = 1  # 슬롯 하나의 시간 수 (1이면 받은 값 그대로, 3이면 3시간씩 묶음)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
HOURLY_VARS = [
    "weather_code",
    "temperature_2m",
    "apparent_temperature",
    "wind_speed_10m",
    "visibility",
    "precipitation",
    "precipitation_probability",
]


def _get(url, params):
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "accu_weather/0.1"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch(cities, forecast_days):
    """여러 도시를 한 번에 요청한다. 시간은 각 도시의 현지 시간대로 받는다. cities 순서대로 결과를 돌려준다."""
    data = _get(FORECAST_URL, {
        "latitude": ",".join(str(c["latitude"]) for c in cities),
        "longitude": ",".join(str(c["longitude"]) for c in cities),
        "hourly": ",".join(HOURLY_VARS),
        "timezone": ",".join(c["timezone"] for c in cities),
        "forecast_days": forecast_days,
    })
    return data if isinstance(data, list) else [data]


def _values(xs):
    return [x for x in xs if x is not None]


def to_slots(data, city_id, today, fetched_at):
    """1시간 값을 SLOT_HOURS 슬롯 행으로 묶는다. today는 수집 시점의 도시 현지 날짜."""
    hourly = data["hourly"]
    groups = {}
    for i, t in enumerate(hourly["time"]):
        start = datetime.fromisoformat(t)
        key = (start.date(), start.hour // SLOT_HOURS * SLOT_HOURS)
        chunk = groups.setdefault(key, {var: [] for var in HOURLY_VARS})
        for var in HOURLY_VARS:
            chunk[var].append(hourly[var][i])

    rows = []
    for (target, hour), chunk in sorted(groups.items()):
        code = codes.representative(chunk["weather_code"])
        temps = _values(chunk["temperature_2m"])
        feels = _values(chunk["apparent_temperature"])
        winds = _values(chunk["wind_speed_10m"])
        vis = _values(chunk["visibility"])
        precip = _values(chunk["precipitation"])
        prob = _values(chunk["precipitation_probability"])
        rows.append({
            "target_date": target.isoformat(),
            "slot": f"{hour:02d}",
            "city_id": city_id,
            "lead_days": (target - today).days,
            "weather": codes.category(code),
            "weather_code": code,
            "temp_max": max(temps) if temps else None,
            "temp_min": min(temps) if temps else None,
            "feel_max": max(feels) if feels else None,
            "feel_min": min(feels) if feels else None,
            "wind_kmh": max(winds) if winds else None,
            "visibility_m": min(vis) if vis else None,
            "precip_mm": round(sum(precip), 2) if precip else None,
            "precip_prob": max(prob) if prob else None,
            "source": SOURCE,
            "fetched_at": fetched_at,
        })
    return rows


def geocode(name, count=5):
    """영어 이름으로 도시 후보를 찾는다. name/country도 영어로 받는다."""
    data = _get(GEOCODING_URL, {"name": name, "count": count, "language": "en"})
    return data.get("results", [])


def lookup_timezone(latitude, longitude):
    """좌표만 있을 때 시간대를 알아낸다."""
    data = _get(FORECAST_URL, {
        "latitude": latitude, "longitude": longitude, "timezone": "auto", "forecast_days": 1,
    })
    return data["timezone"]
