"""설치 TUI 문구 (설치 화면에서만 쓴다). 언어를 추가하려면 LANGUAGES와 TEXT에 같은 키로 넣는다."""

LANGUAGES = [("ko", "한국어"), ("en", "English"), ("ja", "日本語")]

TEXT = {
    "ko": {
        "title": "accu_weather 설치",
        "keys_nav": "Enter 다음 · Esc 이전 · q 종료",
        "lang_title": "언어 선택",
        "lang_body": "설치 화면에서 쓸 언어를 고르세요. (설치 화면에만 적용됩니다)",
        "intro_title": "프로그램 소개",
        "intro_body": (
            "등록한 도시들의 15일 날씨 예보를 매일 도시 현지 시각 22시에 Open-Meteo에서 받아 저장합니다.\n"
            "\n"
            "같은 날짜에 대해 14일 전, 13일 전 … 당일에 각각 어떻게 예보했는지 쌓고, "
            "n일 전 예보가 당일 예보와 얼마나 같았는지 기록합니다.\n"
            "\n"
            "결과는 일별로 그날의 기록을 그대로 보거나, 주별·월별·연도별로 같은 n일 전 예보끼리 평균 내어 볼 수 있습니다. "
            "(조회 화면은 웹으로 추가 예정)\n"
            "\n"
            "데이터는 이 컴퓨터의 data/weather.sqlite3 에 저장됩니다. 컴퓨터를 계속 켜 두어야 합니다."
        ),
        "cron_title": "자동 실행 안내",
        "cron_body": (
            "설치를 마치면 crontab에 아래 한 줄이 등록됩니다. 30분마다 실행되어, "
            "현지 22시가 지났고 오늘 아직 받지 않은 도시만 예보를 받습니다.\n"
            "\n"
            "  {line}\n"
            "\n"
            "받을 도시가 없으면 아무것도 하지 않고 바로 끝납니다. 해제: ./run.sh uninstall"
        ),
        "cities_title": "도시 추가",
        "search_label": "도시 검색 (영어 이름): ",
        "results": "검색 결과",
        "selected": "선택한 도시",
        "registered": "(등록됨)",
        "inactive": "(수집 중단됨)",
        "mark_stop": "(→ 수집 중단)",
        "mark_purge": "(→ 완전 삭제)",
        "unregister_prompt": "{name} 등록 취소: 1 수집 중단(데이터 유지) · 2 완전 삭제(데이터까지) · 그 밖의 키 취소",
        "removed": "뺌: {name}",
        "marked": "{name}: 설치할 때 적용됩니다 (다시 Del: 취소)",
        "unmarked": "{name}: 등록 취소를 취소했습니다",
        "already_stopped": "{name}: 이미 수집 중단된 도시입니다",
        "searching": "검색 중...",
        "no_results": "검색 결과 없음",
        "search_failed": "검색 실패: {e}",
        "already": "이미 선택한 도시입니다",
        "added": "추가: {name}",
        "next_button": "[ 다음 ]",
        "cities_keys": "Tab 칸 이동 · Enter 검색/추가 · Del 빼기/등록 취소 · Esc 검색 지우기/이전",
        "finish_title": "설치",
        "finish_body": "아래 내용으로 설치합니다.",
        "finish_new": "새로 추가할 도시",
        "finish_none": "(없음)",
        "finish_stop": "수집 중단 (데이터 유지)",
        "finish_purge": "완전 삭제 (데이터까지 지움, 되돌릴 수 없음)",
        "finish_cron": "crontab 등록",
        "finish_keys": "Enter 설치 · Esc 이전 · q 종료",
        "done_title": "설치 완료",
        "done_cities": "도시 {n}개를 추가했습니다.",
        "done_removed": "수집 중단 {stopped}개, 완전 삭제 {purged}개.",
        "done_cron": "crontab에 등록했습니다.",
        "done_cron_failed": "crontab 등록 실패: {e}",
        "done_next": "각 도시의 현지 22시에 첫 수집이 시작됩니다. 결과는 logs/ 폴더에 남습니다.",
        "done_keys": "Enter 종료",
        "too_small": "터미널 창을 {w}x{h} 이상으로 넓혀 주세요",
    },
    "en": {
        "title": "accu_weather setup",
        "keys_nav": "Enter next · Esc back · q quit",
        "lang_title": "Language",
        "lang_body": "Choose the language for this setup screen. (Used only during setup)",
        "intro_title": "About",
        "intro_body": (
            "Every day at 22:00 local time of each registered city, this program fetches "
            "the 15-day forecast from Open-Meteo and stores it.\n"
            "\n"
            "For each date it keeps what was forecast 14 days before, 13 days before … and on the day, "
            "and records how close each n-day-ahead forecast was to the same-day forecast.\n"
            "\n"
            "Results can be viewed per day as recorded, or as weekly, monthly and yearly averages of the same n-day-ahead forecasts. "
            "(The viewer will be added as a web page)\n"
            "\n"
            "Data is stored in data/weather.sqlite3 on this computer. The computer must stay on."
        ),
        "cron_title": "Scheduled run",
        "cron_body": (
            "Setup adds the line below to your crontab. It runs every 30 minutes and fetches only "
            "the cities where it is past 22:00 local time and today's forecast has not been fetched yet.\n"
            "\n"
            "  {line}\n"
            "\n"
            "If no city is due, it exits immediately. To remove: ./run.sh uninstall"
        ),
        "cities_title": "Add cities",
        "search_label": "Search city (English name): ",
        "results": "Results",
        "selected": "Selected",
        "registered": "(registered)",
        "inactive": "(stopped)",
        "mark_stop": "(→ stop)",
        "mark_purge": "(→ delete)",
        "unregister_prompt": "Unregister {name}: 1 stop (keep data) · 2 delete (with data) · other key cancel",
        "removed": "Removed: {name}",
        "marked": "{name}: applied on install (Del again to undo)",
        "unmarked": "{name}: unregister undone",
        "already_stopped": "{name}: already stopped",
        "searching": "Searching...",
        "no_results": "No results",
        "search_failed": "Search failed: {e}",
        "already": "Already selected",
        "added": "Added: {name}",
        "next_button": "[ Next ]",
        "cities_keys": "Tab move · Enter search/add · Del remove/unregister · Esc clear/back",
        "finish_title": "Install",
        "finish_body": "The following will be installed.",
        "finish_new": "Cities to add",
        "finish_none": "(none)",
        "finish_stop": "Stop collecting (keep data)",
        "finish_purge": "Delete (including data, cannot be undone)",
        "finish_cron": "crontab entry",
        "finish_keys": "Enter install · Esc back · q quit",
        "done_title": "Done",
        "done_cities": "Added {n} cities.",
        "done_removed": "Stopped {stopped}, deleted {purged}.",
        "done_cron": "Registered in crontab.",
        "done_cron_failed": "crontab registration failed: {e}",
        "done_next": "The first fetch for each city starts at 22:00 local time. Results are written to logs/.",
        "done_keys": "Enter exit",
        "too_small": "Please enlarge the terminal to at least {w}x{h}",
    },
    "ja": {
        "title": "accu_weather インストール",
        "keys_nav": "Enter 次へ · Esc 戻る · q 終了",
        "lang_title": "言語の選択",
        "lang_body": "インストール画面で使う言語を選んでください。（この画面にのみ適用されます）",
        "intro_title": "プログラムの概要",
        "intro_body": (
            "登録した都市の15日間の天気予報を、毎日各都市の現地時間22時に Open-Meteo から取得して保存します。\n"
            "\n"
            "同じ日付について14日前、13日前 … 当日にそれぞれどう予報されたかを蓄積し、"
            "n日前の予報が当日の予報とどれだけ一致したかを記録します。\n"
            "\n"
            "結果は日別にその日の記録をそのまま見るか、週別・月別・年別に同じn日前の予報どうしの平均で見ることができます。"
            "（閲覧画面はWebで追加予定）\n"
            "\n"
            "データはこのコンピュータの data/weather.sqlite3 に保存されます。コンピュータは常に起動しておく必要があります。"
        ),
        "cron_title": "自動実行について",
        "cron_body": (
            "インストールが完了すると、crontab に次の1行が登録されます。30分ごとに実行され、"
            "現地時間22時を過ぎていて今日まだ取得していない都市だけ予報を取得します。\n"
            "\n"
            "  {line}\n"
            "\n"
            "取得する都市がなければ何もせずすぐに終了します。解除: ./run.sh uninstall"
        ),
        "cities_title": "都市の追加",
        "search_label": "都市を検索（英語名）: ",
        "results": "検索結果",
        "selected": "選択した都市",
        "registered": "（登録済み）",
        "inactive": "（取得停止中）",
        "mark_stop": "（→ 取得停止）",
        "mark_purge": "（→ 完全削除）",
        "unregister_prompt": "{name} の登録解除: 1 取得停止（データ保持）· 2 完全削除（データも）· 他のキーで取り消し",
        "removed": "外しました: {name}",
        "marked": "{name}: インストール時に適用されます（もう一度 Del で取り消し）",
        "unmarked": "{name}: 登録解除を取り消しました",
        "already_stopped": "{name}: すでに取得停止中です",
        "searching": "検索中...",
        "no_results": "検索結果がありません",
        "search_failed": "検索に失敗しました: {e}",
        "already": "すでに選択した都市です",
        "added": "追加: {name}",
        "next_button": "[ 次へ ]",
        "cities_keys": "Tab 移動 · Enter 検索/追加 · Del 外す/登録解除 · Esc 検索クリア/戻る",
        "finish_title": "インストール",
        "finish_body": "次の内容でインストールします。",
        "finish_new": "新しく追加する都市",
        "finish_none": "（なし）",
        "finish_stop": "取得停止（データは保持）",
        "finish_purge": "完全削除（データも削除、元に戻せません）",
        "finish_cron": "crontab に登録",
        "finish_keys": "Enter インストール · Esc 戻る · q 終了",
        "done_title": "インストール完了",
        "done_cities": "都市を{n}件追加しました。",
        "done_removed": "取得停止 {stopped}件、完全削除 {purged}件。",
        "done_cron": "crontab に登録しました。",
        "done_cron_failed": "crontab の登録に失敗しました: {e}",
        "done_next": "各都市の現地時間22時に最初の取得が始まります。結果は logs/ フォルダに記録されます。",
        "done_keys": "Enter 終了",
        "too_small": "ターミナルを {w}x{h} 以上に広げてください",
    },
}
