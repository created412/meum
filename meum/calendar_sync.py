# -*- coding: utf-8 -*-
"""
캘린더 연동.

  · GoogleBackend  — Google Calendar API 직접 등록 (공개 API 있음)
  · IcsBackend     — .ics 파일 생성 (삼성 캘린더 가져오기 / 백업 / 오프라인)
  · MultiBackend   — 위 둘에 동시에 저장

삼성 캘린더에 대하여
--------------------
삼성 캘린더에는 외부 프로그램이 일정을 직접 넣을 수 있는 공개 API가 없다.
따라서 다음 경로를 쓴다.

  갤럭시 폰 → 삼성 캘린더 앱 → 캘린더 관리 → Google 계정 켜기

이렇게 해두면 이 프로그램이 Google 캘린더에 넣은 일정이
삼성 캘린더 화면에 그대로 나타난다. 한 번만 설정하면 이후 자동이다.
인터넷이 안 되거나 구글을 쓰지 않을 때를 위해 .ics 묶음 파일도 함께 만든다.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from . import config

CALENDAR_NAME = "업무(브리티)"


# --------------------------------------------------------------------------
# 공통
# --------------------------------------------------------------------------
def _parse_due(due_at: str) -> Tuple[datetime, bool]:
    """(datetime, all_day) 반환."""
    if "T" in due_at:
        return datetime.fromisoformat(due_at), False
    return datetime.fromisoformat(due_at + "T00:00"), True


def _title(task, prefix: str) -> str:
    if task["due_kind"] == "deadline":
        return f"{prefix}{task['title']}"
    return task["title"]


def _description(task) -> str:
    lines = []
    if task["requester"]:
        lines.append(f"요청: {task['requester']}")
    if task["category"]:
        lines.append(f"구분: {task['category']}")
    if task["detail"]:
        lines.append("")
        lines.append(task["detail"])
    if task["warn"]:
        lines.append("")
        lines.append(f"[확인 필요] {task['warn']}")
    lines.append("")
    lines.append(f"(메움 자동 등록 · task#{task['task_id']})")
    return "\n".join(lines)


class CalendarError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# ICS
# --------------------------------------------------------------------------
def _ics_escape(s: str) -> str:
    return (s.replace("\\", "\\\\").replace(";", r"\;")
             .replace(",", r"\,").replace("\n", r"\n"))


def _sequence() -> int:
    """
    수정본을 다시 가져올 때 캘린더가 '갱신'으로 받아들이게 하는 값.
    같은 UID 라도 SEQUENCE 가 커야 새 내용으로 덮어쓴다.
    2020년 이후 경과 분(分) — 단조 증가하며 32비트 안에 들어간다.
    """
    return int((datetime.now() - datetime(2020, 1, 1)).total_seconds() // 60)


def _vevent(task, cfg: dict, uid: str) -> List[str]:
    dt, all_day = _parse_due(task["due_at"])
    if all_day:
        dtstart = f"DTSTART;VALUE=DATE:{dt.strftime('%Y%m%d')}"
        dtend = f"DTEND;VALUE=DATE:{(dt + timedelta(days=1)).strftime('%Y%m%d')}"
    else:
        start = dt - timedelta(minutes=30)
        dtstart = f"DTSTART;TZID=Asia/Seoul:{start.strftime('%Y%m%dT%H%M%S')}"
        dtend = f"DTEND;TZID=Asia/Seoul:{dt.strftime('%Y%m%dT%H%M%S')}"

    alarms = []
    for minutes in cfg.get("reminder_minutes", [1440, 120]):
        alarms += [
            "BEGIN:VALARM",
            f"TRIGGER:-PT{int(minutes)}M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_ics_escape(task['title'])}",
            "END:VALARM",
        ]

    return [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SEQUENCE:{_sequence()}",
        f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
        dtstart,
        dtend,
        f"SUMMARY:{_ics_escape(_title(task, cfg.get('event_title_prefix', '[마감] ')))}",
        f"DESCRIPTION:{_ics_escape(_description(task))}",
        *alarms,
        "END:VEVENT",
    ]


def _wrap_calendar(events: List[str]) -> str:
    return "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Meaum//KR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{CALENDAR_NAME}",
        *events,
        "END:VCALENDAR",
    ])


class IcsBackend:
    """
    삼성 캘린더용 .ics 파일 생성.

    핵심은 UID 를 **할 일마다 고정**하는 것이다.
    UID 가 매번 달라지면 같은 일정을 다시 가져올 때 중복으로 쌓인다.
    고정해 두면 캘린더가 '같은 일정의 수정본'으로 인식해 덮어쓴다.
    """
    provider = "ics"
    label = "삼성 캘린더 파일(.ics)"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.dir = Path(config.ICS_DIR)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._batch: List[List[str]] = []

    @staticmethod
    def make_uid(task_id) -> str:
        """할 일 번호로만 만든다 — 언제 다시 만들어도 같은 값."""
        return f"brity-{task_id}@brity.todo"

    def upsert(self, task, link=None) -> str:
        uid = self.make_uid(task["task_id"])
        ev = _vevent(task, self.cfg, uid)
        self._batch.append(ev)

        if self.cfg.get("ics_write_individual_files", False):
            safe = re.sub(r"[^\w가-힣]+", "_", task["title"])[:40]
            dt, _ = _parse_due(task["due_at"])
            (self.dir / f"{dt:%Y%m%d}_{task['task_id']}_{safe}.ics").write_text(
                _wrap_calendar(ev), encoding="utf-8")
        return uid

    def finish(self) -> Optional[Path]:
        """이번에 저장한 일정을 파일 하나로 묶는다 (폰으로 옮겨 가져오기용)."""
        if not self._batch:
            return None
        events = [line for ev in self._batch for line in ev]
        n = len(self._batch)
        path = self.dir / f"{datetime.now():%Y-%m-%d}_업무일정_{n}건.ics"
        # 같은 날 여러 번 정리하면 덮어쓰지 않고 번호를 붙인다
        if path.exists():
            i = 2
            while True:
                alt = self.dir / f"{datetime.now():%Y-%m-%d}_업무일정_{n}건_{i}.ics"
                if not alt.exists():
                    path = alt
                    break
                i += 1
        path.write_text(_wrap_calendar(events), encoding="utf-8")
        return path


# --------------------------------------------------------------------------
# Google Calendar
# --------------------------------------------------------------------------
class GoogleBackend:
    provider = "google"
    label = "Google 캘린더"
    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def __init__(self, cfg: dict, interactive: bool = True):
        self.cfg = cfg
        self.interactive = interactive
        self.service = self._build_service()
        self.cal_id = self._resolve_calendar()

    # ---- 인증 ----
    @staticmethod
    def token_path() -> Path:
        return Path(config.APP_DIR) / "google_token.json"

    @staticmethod
    def credentials_path(cfg: dict) -> Optional[Path]:
        """client_secret.json 위치. 설정값 → 앱 폴더 → 프로그램 폴더 순으로 찾는다."""
        cand = []
        if cfg.get("google_credentials_file"):
            cand.append(Path(cfg["google_credentials_file"]))
        cand.append(Path(config.APP_DIR) / "client_secret.json")
        try:
            import sys
            base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
            cand.append(base / "client_secret.json")
            cand.append(Path(sys.executable).parent / "client_secret.json")
        except Exception:
            pass
        for p in cand:
            if p and p.exists():
                return p
        return None

    @classmethod
    def is_authorized(cls) -> bool:
        return cls.token_path().exists()

    def _build_service(self):
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError as e:
            raise CalendarError(
                "Google 캘린더 라이브러리가 없습니다.\n"
                "pip install google-api-python-client google-auth-oauthlib") from e

        tp = self.token_path()
        creds = None
        if tp.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(tp), self.SCOPES)
            except Exception:
                creds = None

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    creds = None
            if not creds or not creds.valid:
                if not self.interactive:
                    raise CalendarError(
                        "Google 캘린더 인증이 만료되었습니다.\n"
                        "'지금 정리하기'를 한 번 실행해 다시 로그인해 주세요.")
                cs = self.credentials_path(self.cfg)
                if not cs:
                    raise CalendarError(
                        "Google 인증 파일(client_secret.json)이 없습니다.\n"
                        "처음 설정 화면(메움.exe --setup)에서 Google 캘린더 연결을 먼저 진행해 주세요.")
                flow = InstalledAppFlow.from_client_secrets_file(str(cs), self.SCOPES)
                creds = flow.run_local_server(
                    port=0, prompt="consent",
                    authorization_prompt_message="브라우저에서 Google 로그인을 진행해 주세요…",
                    success_message="연결되었습니다. 창을 닫으셔도 됩니다.")
            config.ensure_dirs()
            tp.write_text(creds.to_json(), encoding="utf-8")

        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    # ---- 전용 캘린더 ----
    def _resolve_calendar(self) -> str:
        """개인 일정과 섞이지 않도록 '업무(브리티)' 캘린더를 쓴다."""
        want = self.cfg.get("google_calendar_id", "")
        if want and want != "auto":
            return want
        try:
            page = None
            while True:
                res = self.service.calendarList().list(pageToken=page).execute()
                for c in res.get("items", []):
                    if c.get("summary") == CALENDAR_NAME:
                        return c["id"]
                page = res.get("nextPageToken")
                if not page:
                    break
            created = self.service.calendars().insert(
                body={"summary": CALENDAR_NAME, "timeZone": "Asia/Seoul",
                      "description": "브리티 쪽지에서 자동으로 정리된 업무 일정"}).execute()
            return created["id"]
        except Exception:
            return "primary"

    # ---- 등록 ----
    def upsert(self, task, link=None) -> str:
        dt, all_day = _parse_due(task["due_at"])
        if all_day:
            start = {"date": dt.strftime("%Y-%m-%d")}
            end = {"date": (dt + timedelta(days=1)).strftime("%Y-%m-%d")}
        else:
            start = {"dateTime": (dt - timedelta(minutes=30)).isoformat(),
                     "timeZone": "Asia/Seoul"}
            end = {"dateTime": dt.isoformat(), "timeZone": "Asia/Seoul"}

        body = {
            "summary": _title(task, self.cfg.get("event_title_prefix", "[마감] ")),
            "description": _description(task),
            "start": start,
            "end": end,
            "reminders": {
                "useDefault": False,
                "overrides": [{"method": "popup", "minutes": int(m)}
                              for m in self.cfg.get("reminder_minutes", [1440, 120])],
            },
        }

        prev = link["event_id"] if link else None
        if prev and not str(prev).endswith("@brity.todo"):
            try:
                ev = self.service.events().patch(
                    calendarId=self.cal_id, eventId=prev, body=body).execute()
                return ev["id"]
            except Exception:
                pass          # 원본이 지워졌으면 새로 만든다
        ev = self.service.events().insert(calendarId=self.cal_id, body=body).execute()
        return ev["id"]

    def finish(self):
        return None


# --------------------------------------------------------------------------
# 여러 곳에 동시 저장
# --------------------------------------------------------------------------
class MultiBackend:
    provider = "multi"

    def __init__(self, backends: List):
        self.backends = backends
        self.errors: List[str] = []

    @property
    def label(self) -> str:
        return " + ".join(b.label for b in self.backends)

    def upsert(self, task, link=None) -> str:
        """
        모든 백엔드에 저장한다.
        추적용 event_id 는 Google 것을 우선한다(수정·삭제에 필요하므로).
        """
        ids = {}
        for b in self.backends:
            try:
                ids[b.provider] = b.upsert(task, link)
            except Exception as e:
                self.errors.append(f"{b.label}: {e}")
        if not ids:
            raise CalendarError("; ".join(self.errors[-2:]) or "저장 실패")
        return ids.get("google") or next(iter(ids.values()))

    def finish(self):
        out = []
        for b in self.backends:
            try:
                r = b.finish()
                if r:
                    out.append(r)
            except Exception:
                pass
        return out[0] if out else None


# --------------------------------------------------------------------------
def build(cfg: dict, interactive: bool = True):
    """
    설정 `calendar_backends` 목록대로 백엔드를 만든다.
    Google 연결에 실패해도 .ics 는 남도록 한다.
    """
    names = cfg.get("calendar_backends")
    if not names:
        legacy = cfg.get("calendar_backend", "ics")
        names = [legacy]

    built, errors = [], []
    for n in names:
        try:
            if n == "google":
                built.append(GoogleBackend(cfg, interactive=interactive))
            elif n == "ics":
                built.append(IcsBackend(cfg))
        except Exception as e:
            errors.append(f"{n}: {e}")

    if not built:
        # 최소한 파일로는 남긴다
        built.append(IcsBackend(cfg))
        errors.append("Google 연결에 실패해 .ics 파일로만 저장합니다.")

    m = MultiBackend(built)
    m.errors.extend(errors)
    return m
