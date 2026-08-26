# -*- coding: utf-8 -*-
"""설정 로드/저장. 외부 의존성 없이 JSON 사용."""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "BrityTodo"
CONFIG_PATH = APP_DIR / "config.json"
STATE_PATH = APP_DIR / "state.db"
LOG_DIR = APP_DIR / "logs"
ICS_DIR = APP_DIR / "ics"

DEFAULTS = {
    # --- 실행 ---
    # 자동 점검 시각은 설치 마법사에서 사용자가 직접 입력한다.
    # 아래 값은 입력 전의 임시값일 뿐이며, times_confirmed 가 True 가 되기 전에는
    # 마법사가 빈칸으로 시작해 반드시 직접 입력하게 한다.
    "run_time": "08:40",
    "run_time_lunch": "12:40",
    "times_confirmed": False,        # 사용자가 시각을 직접 입력·등록했는가

    # 예약 실행(아침·저녁)은 창을 띄우지 않고 조용히 정리한다.
    #   · 확신도 높은 할 일 → 바로 저장되어 패널에 나타남
    #   · 애매한 것        → 패널에 '미확정'으로 표시, 교사가 패널에서 판단
    # 바로가기로 직접 실행할 때만 확인 창이 뜬다.
    "auto_mode": True,

    # --- 오늘 마감 알람 (깜빡함 방지) ---
    "alarm_enabled": True,
    "remind_before_min": 60,        # 마감 몇 분 전에 미리 알릴까
    "remind_repeat_min": 120,       # 미완료 반복 알림 간격(분)
    "extra_run_times": [],           # 예: ["12:30", "16:30"]
    "first_run_lookback_days": 14,   # 최초 실행 시 소급 범위
    "max_open_per_run": 30,          # 한 번에 열어볼 쪽지 최대 수(안전장치)

    # --- 어디서 모을까 ---
    # brity : 브리티 메신저 (삼성SDS)
    # goe   : GOE메신저 (경기도교육청, AtMessenger7)
    "sources": ["brity", "goe"],

    # --- 수집 정책 ---
    # full : 쪽지를 열어 본문 전문 확보 (정확도 최고, '읽음' 처리됨)
    # preview : 목록 미리보기만 사용 (브리티 상태 불변, 마감일 놓칠 수 있음)
    "collect_mode": "full",
    "launch_brity_if_closed": True,
    "restore_cursor": True,

    # --- 추출 ---
    # rule : 규칙 기반 (기본, 외부 전송 없음)
    # claude : Claude API 사용 (정확도 향상, 본문이 외부로 전송됨)
    "extractor": "rule",
    "claude_model": "claude-sonnet-5",
    "anthropic_api_key": "",         # 비우면 환경변수 ANTHROPIC_API_KEY 사용
    "mask_phone_numbers": True,

    # --- 승인 정책 ---
    "auto_approve_confidence": 0.85,
    "review_min_confidence": 0.60,

    # --- 캘린더 ---
    # 저장할 곳 (여러 개 동시 지정 가능)
    #   ics    : 삼성 캘린더로 가져올 .ics 파일 생성 — 계정·비밀번호가 필요 없다
    #   google : Google 캘린더 직접 등록 (선택). 구글은 2025년부터 아이디·비밀번호
    #            로그인을 완전히 막았으므로, 쓰려면 각자 OAuth 연결이 필요하다.
    #            기본값에서 빼둔 이유다.
    "calendar_backends": ["ics"],
    "calendar_backend": "ics",          # (구버전 설정 호환용)
    "google_calendar_id": "auto",       # auto = '업무(브리티)' 캘린더 자동 생성
    "google_credentials_file": "",      # client_secret.json 경로

    # --- 삼성 캘린더로 옮기기 ---
    # USB로 연결된 폰의 다운로드 폴더에 .ics 를 자동으로 넣는다.
    # 폰이 없으면 조용히 건너뛴다.
    "send_to_phone": False,          # 자체 달력을 쓰므로 기본 꺼짐
    "phone_device_name": "",            # 비우면 자동 탐색
    "open_ics_folder": False,
    "ics_write_individual_files": False,  # 일정마다 파일을 따로 만들지 여부
    "deadline_default_time": "17:00",
    "reminder_minutes": [1440, 120],  # 1일 전, 2시간 전
    "event_title_prefix": "[마감] ",

    # --- 구글 캘린더 수시 동기화 ---
    # 패널이 떠 있는 동안 주기적으로 캘린더를 현재 상태에 맞춘다.
    # (완료 체크한 일은 캘린더에서도 빠진다)
    "google_sync_minutes": 10,

    # --- 바탕화면 할 일 패널 ---
    "widget_enabled": True,          # 정리가 끝나면 패널을 띄운다
    "widget_width": 380,
    "widget_x": None,                # 비우면 화면 오른쪽에 붙는다
    "widget_y": None,
    "widget_always_on_top": False,   # 머리말의 📌 로 바꿀 수 있다

    # --- 사용자 ---
    "my_name": "",                   # 비우면 브리티 화면에서 자동 인식 시도
    "school": "",
}


def ensure_dirs() -> None:
    for d in (APP_DIR, LOG_DIR, ICS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    ensure_dirs()
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    else:
        save(cfg)
    return cfg


def save(cfg: dict) -> None:
    """설정 전체를 덮어쓴다. 방금 파일을 읽은 쪽(설치 마법사)만 써야 한다."""
    ensure_dirs()
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def update(**changes) -> dict:
    """
    바꾸려는 항목만 골라 저장한다. 갱신된 설정을 돌려준다.

    오래 떠 있는 프로그램(바탕화면 패널)은 켜질 때 읽은 설정 사본을 들고 있다.
    그 사본을 save() 로 통째로 쓰면, 그 사이 다른 곳(설치 마법사)에서 바꾼 값이
    조용히 되돌아간다. 실제로 마법사에서 정한 점검 시각이 패널의 탭 클릭 한 번에
    옛 값으로 돌아간 적이 있다. 그래서 파일을 다시 읽어 해당 항목만 고쳐 쓴다.
    """
    ensure_dirs()
    current = {}
    if CONFIG_PATH.exists():
        try:
            current = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            current = {}
    current.update(changes)
    CONFIG_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    merged = dict(DEFAULTS)
    merged.update(current)
    return merged
