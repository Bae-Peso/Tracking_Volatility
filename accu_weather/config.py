"""경로와 config.toml 설정."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "collect": {
        "fetch_hour": 22,  # 도시 현지 시각으로 이 시각 이후 수집분을 그날의 확정 예보로 본다
        "forecast_days": 15,  # 오늘 + 14일
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
