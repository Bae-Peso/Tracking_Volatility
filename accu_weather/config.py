"""경로와 config.toml 설정."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "collect": {
        "fetch_hour": 22,  # 도시 현지 시각으로 이 시각 이후 수집분을 그날의 확정 예보로 본다
        "forecast_days": 15,  # 오늘 + 14일
    },
    "accuracy": {
        "temp_worst_c": 5.0,  # d0와 평균 이만큼(℃) 이상 다르면 기온·체감온도 항목 최악
        "rain_worst_mm": 10.0,  # 0mm ↔ 이만큼 차이(로그 척도)면 강수량 항목 최악
        "weights": {"temp": 0.2, "feel": 0.2, "prob": 0.2, "rain": 0.2, "weather": 0.2},
    },
    "paths": {
        "db": "data/weather.sqlite3",
        "cities": "cities.txt",
    },
}


def load():
    cfg = {section: dict(values) for section, values in DEFAULTS.items()}
    path = ROOT / "config.toml"
    if path.exists():
        with path.open("rb") as f:
            for section, values in tomllib.load(f).items():
                cfg.setdefault(section, {}).update(values)
    return cfg


def resolve(path):
    """config의 상대 경로는 프로젝트 루트 기준."""
    path = Path(path)
    return path if path.is_absolute() else ROOT / path
