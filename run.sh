#!/usr/bin/env bash
# cron 진입점: 매일 22:00, 23:00, 23:30 실행.
# 이미 오늘 22시 이후에 받았으면 fetch_forecast.py가 알아서 건너뛴다.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p data logs

log="logs/$(date +%Y-%m).log"
exec 9>data/.lock
if ! flock -n 9; then
    echo "$(date '+%F %T') skip: previous run still in progress" >> "$log"
    exit 0
fi

status=0
timeout 120 python3 fetch_forecast.py >> "$log" 2>&1 || status=$?
if [ "$status" -ne 0 ]; then
    echo "$(date '+%F %T') FAILED (exit $status)" >> "$log"
    exit "$status"
fi
