#!/usr/bin/env bash
# cron 진입점: 30분마다 실행.
# 현지 22시가 지났고 오늘 아직 안 받은 도시만 accu_weather가 골라서 받는다.
#   ./run.sh install    crontab에 30분 간격으로 등록 (기존 run.sh 줄은 교체)
#   ./run.sh uninstall  crontab에서 run.sh 줄 제거
set -euo pipefail
cd "$(dirname "$0")"
script="$PWD/$(basename "$0")"
cron_line="*/30 * * * *  $script"

# run.sh가 들어간 줄만 빼고 기존 crontab을 그대로 출력
other_cron_lines() {
    crontab -l 2>/dev/null | grep -vF "$script" || true
}

# 기존 crontab을 다 읽은 뒤에 쓴다 (읽으면서 덮어쓰면 다른 줄이 날아갈 수 있음)
case "${1:-}" in
    install)
        others="$(other_cron_lines)"
        printf '%s\n%s\n' "$others" "$cron_line" | sed '/./,$!d' | crontab -
        echo "installed: $cron_line"
        exit 0
        ;;
    uninstall)
        others="$(other_cron_lines)"
        printf '%s\n' "$others" | sed '/./,$!d' | crontab -
        echo "removed: $script"
        exit 0
        ;;
esac

mkdir -p data logs

log="logs/$(date +%Y-%m).log"
exec 9>data/.lock
if ! flock -n 9; then
    echo "$(date '+%F %T') skip: previous run still in progress" >> "$log"
    exit 0
fi

status=0
timeout 120 python3 -m accu_weather collect >> "$log" 2>&1 || status=$?
if [ "$status" -ne 0 ]; then
    echo "$(date '+%F %T') FAILED (exit $status)" >> "$log"
    exit "$status"
fi
