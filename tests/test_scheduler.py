"""Docker용 상주 실행: 정각·30분 경계, 반복, 실패해도 계속, 종료 신호."""

import io
import signal
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

from accu_weather import collect, db, scheduler
from tests.fakes import cfg


class NextTickTest(unittest.TestCase):
    def test_다음_정각_30분(self):
        cases = [
            (datetime(2026, 10, 23, 12, 0, 0), datetime(2026, 10, 23, 12, 30)),  # 경계 위면 그다음
            (datetime(2026, 10, 23, 12, 29, 59), datetime(2026, 10, 23, 12, 30)),
            (datetime(2026, 10, 23, 12, 30, 0, 1), datetime(2026, 10, 23, 13, 0)),
            (datetime(2026, 10, 23, 23, 45), datetime(2026, 10, 24, 0, 0)),  # 날짜 넘어감
        ]
        for now, expected in cases:
            self.assertEqual(scheduler.next_tick(now), expected, now)


class ServeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.cfg = cfg()
        self.cfg["paths"] = {**self.cfg["paths"], "db": str(Path(self.dir.name) / "t.sqlite3")}
        old = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, old)

    def tearDown(self):
        self.dir.cleanup()

    def errors(self):
        conn = db.connect(Path(self.cfg["paths"]["db"]))
        try:
            return [r["message"] for r in conn.execute("SELECT message FROM error_log")]
        finally:
            conn.close()

    def test_시작하자마자_한_번_그다음은_경계까지_잠듦(self):
        sleeps = []
        with mock.patch.object(collect, "run") as run, redirect_stdout(io.StringIO()):
            scheduler.serve(self.cfg, now=lambda: datetime(2026, 10, 23, 12, 10, 0),
                            sleep=sleeps.append, max_runs=3)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleeps, [1200.0, 1200.0])  # 12:10 → 12:30

    def test_fetch_실패나_예상_못_한_오류가_나도_멈추지_않음(self):
        effects = [SystemExit("fetch failed (Osaka): 503"), RuntimeError("boom"), None]
        out = io.StringIO()
        with mock.patch.object(collect, "run", side_effect=effects) as run, redirect_stdout(out), \
                mock.patch("traceback.print_exc"):
            scheduler.serve(self.cfg, sleep=lambda s: None, max_runs=3)
        self.assertEqual(run.call_count, 3)
        self.assertIn("fetch failed (Osaka): 503", out.getvalue())
        self.assertEqual(self.errors(), ["collect error: RuntimeError: boom"])  # fetch 실패는 collect가 직접 남김

    def test_종료_신호를_받으면_조용히_끝남(self):
        def stop(_):
            scheduler._stop(signal.SIGTERM, None)

        out = io.StringIO()
        with mock.patch.object(collect, "run"), redirect_stdout(out):
            scheduler.serve(self.cfg, sleep=stop)
        self.assertIn("stopped", out.getvalue())
        self.assertIs(signal.getsignal(signal.SIGTERM), scheduler._stop)


if __name__ == "__main__":
    unittest.main()
