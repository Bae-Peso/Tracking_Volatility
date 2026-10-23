"""run.sh install / uninstall. 진짜 crontab 대신 파일에 읽고 쓰는 가짜 crontab을 쓴다."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from accu_weather.config import ROOT

RUN_SH = ROOT / "run.sh"
LINE = f"*/30 * * * *  {RUN_SH}"

FAKE_CRONTAB = """#!/usr/bin/env bash
case "$1" in
  -l) [ -f "$CRONTAB_FILE" ] && cat "$CRONTAB_FILE" || { echo "no crontab" >&2; exit 1; } ;;
  -)  cat > "$CRONTAB_FILE" ;;
esac
"""


class RunShTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        tmp = Path(self.dir.name)
        (tmp / "crontab").write_text(FAKE_CRONTAB)
        (tmp / "crontab").chmod(0o755)
        self.file = tmp / "crontab.txt"
        self.env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "CRONTAB_FILE": str(self.file)}

    def tearDown(self):
        self.dir.cleanup()

    def run_sh(self, arg):
        subprocess.run(["bash", str(RUN_SH), arg], env=self.env, check=True, capture_output=True)

    def test_빈_crontab에_install(self):
        self.run_sh("install")
        self.assertEqual(self.file.read_text(), LINE + "\n")

    def test_예전_줄은_교체하고_다른_줄은_유지_여러번_해도_한_줄(self):
        self.file.write_text(f'MAILTO=""\n0 22 * * *  {RUN_SH}\n0 23 * * *  {RUN_SH}\n30 4 * * 0  echo backup\n')
        self.run_sh("install")
        self.run_sh("install")
        self.assertEqual(self.file.read_text(), f'MAILTO=""\n30 4 * * 0  echo backup\n{LINE}\n')

    def test_uninstall은_run_sh_줄만_제거(self):
        self.file.write_text(f"30 4 * * 0  echo backup\n{LINE}\n")
        self.run_sh("uninstall")
        self.assertEqual(self.file.read_text(), "30 4 * * 0  echo backup\n")


if __name__ == "__main__":
    unittest.main()
