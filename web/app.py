"""웹 조회 (읽기 전용, 로그인 없음).

    gunicorn "web.app:create_app()"        # Docker (compose의 web 서비스)
    flask --app web.app run                # 개발용

화면은 templates/index.html + static/app.js 한 장이고, 데이터는 아래 /api/* 가 JSON으로 준다.
"""

import sqlite3
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from accu_weather import config
from . import queries


class BadRequest(ValueError):
    """입력 오류. 문구 대신 코드를 보내고, 화면이 언어에 맞게 보여준다 (i18n의 err.*)."""

    def __init__(self, code, detail=None):
        super().__init__(code)
        self.code = code
        self.detail = detail


def create_app(db_path=None):
    app = Flask(__name__)
    cfg = config.load()
    acc_cfg = cfg["accuracy"]
    path = Path(db_path) if db_path else config.resolve(cfg["paths"]["db"])

    def open_db():
        if not path.exists():
            raise FileNotFoundError(path)
        return queries.connect_ro(path)

    def arg(name, default=None):
        value = request.args.get(name, default)
        if value is None:
            raise BadRequest("missing_param", name)
        return value

    def arg_date(name):
        try:
            return date.fromisoformat(arg(name)).isoformat()
        except ValueError:
            raise BadRequest("bad_date", name)

    def arg_city(conn):
        c = queries.city(conn, arg("city"))
        if c is None:
            raise BadRequest("unknown_city")
        return c

    def arg_range(max_days=400):
        try:
            return queries.clamp_range(arg_date("start"), arg_date("end"), max_days)
        except queries.RangeTooLong as e:
            raise BadRequest("range_too_long", e.max_days)

    def api(handler):
        """DB를 열고 handler(conn)의 결과를 JSON으로. 입력 오류 400, DB 없음 503."""
        try:
            conn = open_db()
        except (FileNotFoundError, sqlite3.OperationalError):
            return jsonify(error="no_data"), 503
        try:
            return jsonify(handler(conn))
        except BadRequest as e:
            return jsonify(error=e.code, detail=e.detail), 400
        finally:
            conn.close()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/meta")
    def meta():
        return jsonify(queries.meta(acc_cfg))

    @app.get("/api/cities")
    def cities():
        return api(lambda conn: [{**c, "today": queries.local_today(c["timezone"])} for c in queries.cities(conn)])

    @app.get("/api/errors")
    def errors():
        return api(queries.errors)

    @app.get("/api/calendar")
    def calendar():
        def handler(conn):
            c = arg_city(conn)
            start, end = arg_range()
            metric = arg("metric", "score")
            if metric not in queries.CALENDAR_METRICS:
                raise BadRequest("unknown_metric", metric)
            return {"city": c, "start": start, "end": end, "metric": metric,
                    "days": queries.calendar(conn, c["city_id"], start, end, metric, acc_cfg)}
        return api(handler)

    @app.get("/api/day")
    def day():
        def handler(conn):
            c = arg_city(conn)
            return {"city": c, **queries.day(conn, c["city_id"], arg_date("date"), acc_cfg)}
        return api(handler)

    @app.get("/api/series")
    def series():
        def handler(conn):
            c = arg_city(conn)
            start, end = arg_range(queries.SERIES_MAX_DAYS)
            metric = arg("metric", "temp_max")
            step = arg("step", "slot")
            hours = arg("hours", "1")
            if metric not in queries.SERIES_METRICS:
                raise BadRequest("unknown_metric", metric)
            if step not in ("slot", "day"):
                raise BadRequest("unknown_metric", step)
            if hours not in [str(n) for n in queries.SERIES_HOURS]:
                raise BadRequest("unknown_metric", hours)
            return {"city": c, "start": start, "end": end, "metric": metric,
                    **queries.series(conn, c["city_id"], start, end, metric, step, int(hours))}
        return api(handler)

    return app
