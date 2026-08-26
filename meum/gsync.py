# -*- coding: utf-8 -*-
"""
구글 캘린더 수시 동기화.

아침에 한 번만 넣고 끝나면, 그 뒤에 생긴 변화(완료 체크·마감일 수정)가
캘린더에 반영되지 않는다. 그래서 패널이 떠 있는 동안 주기적으로 맞춘다.

맞추는 규칙
  · 미완료인데 캘린더에 없다      → 새로 만든다
  · 미완료인데 마감이 바뀌었다     → 고친다
  · 완료로 체크했다               → 캘린더에서 지운다
  · 구글 연결이 없거나 실패했다     → 조용히 넘어간다 (패널은 그대로 동작)

구글 계정 연결은 각자 자기 계정으로 한 번만 하면 된다.
비밀번호는 이 프로그램이 보지 않는다 — 구글 로그인 창에서만 입력한다.
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable, Optional, Tuple

from . import calendar_sync, config
from .state import State


class SyncResult:
    def __init__(self):
        self.created = 0
        self.updated = 0
        self.removed = 0
        self.failed = 0
        self.error: Optional[str] = None

    @property
    def changed(self) -> int:
        return self.created + self.updated + self.removed

    def summary(self) -> str:
        if self.error:
            return f"구글 동기화 실패 — {self.error[:40]}"
        if not self.changed:
            return "구글 캘린더 최신"
        bits = []
        if self.created:
            bits.append(f"추가 {self.created}")
        if self.updated:
            bits.append(f"수정 {self.updated}")
        if self.removed:
            bits.append(f"삭제 {self.removed}")
        return "구글 " + " · ".join(bits)


def enabled(cfg: dict) -> bool:
    return "google" in (cfg.get("calendar_backends") or [])


def connected() -> bool:
    try:
        return calendar_sync.GoogleBackend.is_authorized()
    except Exception:
        return False


def sync_now(cfg: Optional[dict] = None) -> SyncResult:
    """
    지금 상태를 구글 캘린더에 맞춘다. 화면을 멈추지 않도록 짧게 끝낸다.
    """
    cfg = cfg or config.load()
    res = SyncResult()
    if not enabled(cfg):
        res.error = "구글 캘린더를 쓰지 않도록 설정되어 있습니다"
        return res
    if not connected():
        res.error = "구글 계정이 연결되지 않았습니다"
        return res

    try:
        backend = calendar_sync.GoogleBackend(cfg, interactive=False)
    except Exception as e:
        res.error = str(e)
        return res

    st = State()
    try:
        # 1) 미완료 항목 반영
        for row in st.open_tasks():
            if not row["due_at"]:
                continue                    # 기한 없는 것은 캘린더에 넣지 않는다
            link = st.get_link(row["task_id"])
            already = link and link["event_id"] and link["provider"] == "google"
            if already and (link["last_due_at"] == row["due_at"]):
                continue                    # 바뀐 게 없다
            try:
                event_id = backend.upsert(row, link if already else None)
                st.link_event(row["task_id"], "google", event_id, row["due_at"])
                if already:
                    res.updated += 1
                else:
                    res.created += 1
            except Exception:
                res.failed += 1

        # 2) 완료한 항목은 캘린더에서 뺀다
        for row in st.recently_done(limit=60):
            link = st.get_link(row["task_id"])
            if not (link and link["event_id"] and link["provider"] == "google"):
                continue
            try:
                backend.service.events().delete(
                    calendarId=backend.cal_id, eventId=link["event_id"]).execute()
            except Exception:
                pass                         # 이미 지워졌으면 그만이다
            st.con.execute("DELETE FROM calendar_links WHERE task_id=?",
                           (row["task_id"],))
            st.con.commit()
            res.removed += 1
    except Exception as e:
        res.error = str(e)
    finally:
        st.close()
    return res


def sync_in_background(cfg: Optional[dict] = None,
                       done: Optional[Callable[[SyncResult], None]] = None) -> None:
    """패널이 멈추지 않도록 딴 갈래에서 돌린다."""
    def work():
        r = sync_now(cfg)
        if done:
            done(r)

    threading.Thread(target=work, daemon=True).start()
