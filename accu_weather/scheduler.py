"""Docker용 상주 실행: 매 정각·30분마다 collect를 돌린다 (컨테이너 안에는 cron이 없으므로).

python3 -m accu_weather serve
- 시작하자마자 한 번, 그 뒤로 매 :00 / :30에 실행한다. 받을 도시가 없으면 아무것도 출력하지 않는다.
- 한 번의 실패로 멈추지 않는다. 실패는 error_log와 표준 출력(docker logs)에 남는다.
- docker stop(SIGTERM)을 받으면 바로 끝낸다.
"""

import signal
import time
import traceback
from datetime import datetime, timedelta

from . import collect, config, db

INTERVAL_MIN = 30


def next_tick(now, minutes=INTERVAL_MIN):
    """now 다음의 정각·30분 경계 (now가 경계에 딱 맞아도 그다음)."""
    base = now.replace(minute=0, second=0, microsecond=0)
    return base + timedelta(minutes=(now.minute // minutes + 1) * minutes)


def run_once(cfg):
    conn = db.connect(config.resolve(cfg["paths"]["db"]))
    try:
        collect.run(conn, cfg)
    except SystemExit as e:  # fetch 실패: collect가 error_log에 남기고 메시지를 넘겨줌
        print(e, flush=True)
    except Exception as e:
        db.log_error(conn, f"collect error: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        conn.close()


def _stop(signum, frame):
    raise KeyboardInterrupt  # run_once의 except에 걸리지 않게 SystemExit 대신


def serve(cfg, now=datetime.now, sleep=time.sleep, max_runs=None):
    signal.signal(signal.SIGTERM, _stop)  # 컨테이너 PID 1은 핸들러가 없으면 SIGTERM을 무시함
    print(f"{db.utc_now()} accu_weather serve: collect every {INTERVAL_MIN} min", flush=True)
    runs = 0
    try:
        while True:
            run_once(cfg)
            runs += 1
            if max_runs is not None and runs >= max_runs:
                return
            t = now()
            sleep(max(1.0, (next_tick(t) - t).total_seconds()))
    except KeyboardInterrupt:
        print(f"{db.utc_now()} accu_weather serve: stopped", flush=True)
