"""CLI 진입점.

사용법:
    python3 -m accu_weather setup                   # 설치 TUI (언어 → 소개 → 자동 실행 안내 → 도시 추가 → 설치)
    python3 -m accu_weather collect                 # 현지 22시가 지난 도시만 받음 (cron 30분 간격)
    python3 -m accu_weather collect --force         # 시각과 상관없이 모든 활성 도시를 받음
    python3 -m accu_weather recompute [--city <id>] # 정확도 전체 재계산 (기준값·가중치를 바꾼 뒤)
    python3 -m accu_weather city add "Osaka"        # 영어 이름으로 검색, 후보를 번호로 선택
    python3 -m accu_weather city add "Osaka" --lat 34.70 --lon 135.50   # 좌표 직접 지정
    python3 -m accu_weather city list [--all]
    python3 -m accu_weather city disable <id> [--purge]
    python3 -m accu_weather city enable <id>
    python3 -m accu_weather city export [path]      # 도시 목록 → cities.txt
    python3 -m accu_weather city import [path]      # cities.txt → 도시 목록 (city_id 유지)
<id>는 city list에 나오는 앞 8자리만 입력해도 된다.
"""

import argparse
import csv
import sqlite3
import sys

from . import accuracy, collect, config, db
from .sources import openmeteo


def cmd_collect(conn, cfg, args):
    ids = [db.find_city(conn, p)["city_id"] for p in args.city] if args.city else None
    try:
        collect.run(conn, cfg, force=args.force, city_ids=ids)
    except Exception as e:  # 예상 못 한 오류도 웹 알림용으로 남긴다 (fetch 실패는 collect가 직접 남김)
        db.log_error(conn, f"collect error: {type(e).__name__}: {e}")
        raise


def cmd_setup(conn, cfg, args):
    from . import setup_tui  # curses는 setup에서만 불러옴

    setup_tui.main(conn)


def cmd_recompute(conn, cfg, args):
    city_id = db.find_city(conn, args.city)["city_id"] if args.city else None
    print(f"recomputed {accuracy.recompute(conn, cfg, city_id)} accuracy rows")


def _pick(candidates, pick):
    for i, c in enumerate(candidates, 1):
        region = ", ".join(x for x in (c.get("admin1"), c.get("country")) if x)
        print(f"{i}) {c['name']}, {region}  ({c['latitude']:.2f}, {c['longitude']:.2f})  {c['timezone']}")
    if pick is None:
        answer = input("번호 선택 (엔터: 취소): ").strip()
        if not answer:
            raise SystemExit("취소")
        pick = int(answer)
    if not 1 <= pick <= len(candidates):
        raise SystemExit(f"1~{len(candidates)} 중에서 선택")
    return candidates[pick - 1]


def cmd_city_add(conn, cfg, args):
    if (args.lat is None) != (args.lon is None):
        raise SystemExit("--lat과 --lon은 함께 지정")
    if args.lat is not None:
        tz = args.timezone or openmeteo.lookup_timezone(args.lat, args.lon)
        name, country, lat, lon = args.name, args.country, args.lat, args.lon
    else:
        candidates = openmeteo.geocode(args.name)
        if not candidates:
            raise SystemExit(f"'{args.name}' 검색 결과 없음 (영어 이름으로 검색)")
        c = _pick(candidates, args.pick)
        name, country, lat, lon = c["name"], c.get("country"), c["latitude"], c["longitude"]
        tz = args.timezone or c["timezone"]
    try:
        city_id = db.add_city(conn, name, country, lat, lon, tz)
    except sqlite3.IntegrityError:
        raise SystemExit(f"({lat:.2f}, {lon:.2f}) 좌표의 도시가 이미 등록되어 있음")
    print(f"added {city_id[:8]} {name} ({lat:.2f}, {lon:.2f}) {tz}")


def cmd_city_list(conn, cfg, args):
    for c in db.list_cities(conn, active_only=not args.all):
        state = "" if c["active"] else "  [disabled]"
        print(f"{c['city_id'][:8]}  {c['name']}, {c['country'] or '-'}  "
              f"({c['latitude']:.2f}, {c['longitude']:.2f})  {c['timezone']}{state}")


def cmd_city_disable(conn, cfg, args):
    city = db.find_city(conn, args.id)
    if args.purge:
        answer = input(f"{city['name']}의 도시 정보와 수집한 모든 데이터를 지웁니다. 계속할까요? [y/N] ")
        if answer.strip().lower() != "y":
            raise SystemExit("취소")
        db.purge_city(conn, city["city_id"])
        print(f"purged {city['name']}")
    else:
        db.set_active(conn, city["city_id"], False)
        print(f"disabled {city['name']} (데이터는 유지)")


def cmd_city_enable(conn, cfg, args):
    city = db.find_city(conn, args.id)
    db.set_active(conn, city["city_id"], True)
    print(f"enabled {city['name']}")


def cmd_city_export(conn, cfg, args):
    path = config.resolve(args.path or cfg["paths"]["cities"])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(db.CITY_COLS)
        for c in db.list_cities(conn):
            w.writerow([c[col] for col in db.CITY_COLS])
    print(f"exported to {path}")


def cmd_city_import(conn, cfg, args):
    path = config.resolve(args.path or cfg["paths"]["cities"])
    existing = {c["city_id"] for c in db.list_cities(conn)}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row["city_id"] in existing:
                continue
            try:
                db.add_city(conn, row["name"], row["country"] or None, float(row["latitude"]),
                            float(row["longitude"]), row["timezone"], city_id=row["city_id"],
                            active=int(row["active"]), added_at=row["added_at"])
                print(f"imported {row['city_id'][:8]} {row['name']}")
            except sqlite3.IntegrityError:
                print(f"skip {row['name']}: 같은 좌표에 다른 city_id가 이미 있음", file=sys.stderr)


def build_parser():
    p = argparse.ArgumentParser(prog="accu_weather")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("setup", help="설치 TUI")
    c.set_defaults(func=cmd_setup)

    c = sub.add_parser("collect", help="예보 수집")
    c.add_argument("--force", action="store_true", help="시각·중복 확인 없이 바로 받음")
    c.add_argument("--city", action="append", metavar="ID", help="이 도시만 (여러 번 지정 가능)")
    c.set_defaults(func=cmd_collect)

    c = sub.add_parser("recompute", help="정확도 전체 재계산")
    c.add_argument("--city", metavar="ID", help="이 도시만")
    c.set_defaults(func=cmd_recompute)

    city = sub.add_parser("city", help="도시 관리").add_subparsers(dest="city_cmd", required=True)

    a = city.add_parser("add", help="도시 추가")
    a.add_argument("name", help="영어 도시 이름")
    a.add_argument("--lat", type=float)
    a.add_argument("--lon", type=float)
    a.add_argument("--country")
    a.add_argument("--timezone", help="예: Asia/Tokyo (생략하면 자동)")
    a.add_argument("--pick", type=int, help="검색 후보 번호 (생략하면 물어봄)")
    a.set_defaults(func=cmd_city_add)

    a = city.add_parser("list", help="도시 목록")
    a.add_argument("--all", action="store_true", help="수집 중단된 도시도 표시")
    a.set_defaults(func=cmd_city_list)

    a = city.add_parser("disable", help="수집 중단 (데이터 유지)")
    a.add_argument("id")
    a.add_argument("--purge", action="store_true", help="도시와 데이터를 완전히 삭제")
    a.set_defaults(func=cmd_city_disable)

    a = city.add_parser("enable", help="수집 재개")
    a.add_argument("id")
    a.set_defaults(func=cmd_city_enable)

    for name, func, help_ in (("export", cmd_city_export, "도시 목록 → 파일"),
                              ("import", cmd_city_import, "파일 → 도시 목록")):
        a = city.add_parser(name, help=help_)
        a.add_argument("path", nargs="?", help="기본값: config.toml의 paths.cities")
        a.set_defaults(func=func)
    return p


def main():
    args = build_parser().parse_args()
    cfg = config.load()
    conn = db.connect(config.resolve(cfg["paths"]["db"]))
    try:
        args.func(conn, cfg, args)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
