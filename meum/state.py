# -*- coding: utf-8 -*-
"""로컬 상태 저장소 (SQLite). 중복 방지·완료 상태·캘린더 매핑."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    msg_id       TEXT PRIMARY KEY,
    source       TEXT DEFAULT 'brity',
    list_key     TEXT UNIQUE,
    thread_key   TEXT,
    subject      TEXT,
    sender       TEXT,
    sender_org   TEXT,
    received_at  TEXT,
    body_latest  TEXT,
    body_raw     TEXT,
    attachments  TEXT,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT DEFAULT 'brity',
    msg_id      TEXT,
    thread_key  TEXT,
    title       TEXT,
    detail      TEXT,
    due_at      TEXT,
    due_kind    TEXT,
    requester   TEXT,
    category    TEXT,
    confidence  REAL,
    status      TEXT DEFAULT 'pending',
    warn        TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS calendar_links (
    task_id     INTEGER PRIMARY KEY,
    provider    TEXT,
    event_id    TEXT,
    synced_at   TEXT,
    last_due_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT,
    finished_at TEXT,
    trigger     TEXT,
    window_from TEXT,
    collected   INTEGER DEFAULT 0,
    extracted   INTEGER DEFAULT 0,
    synced      INTEGER DEFAULT 0,
    status      TEXT,
    error       TEXT
);

CREATE TABLE IF NOT EXISTS school_events (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT,
    start_date TEXT,               -- YYYY-MM-DD
    end_date   TEXT,               -- 여러 날이면 마지막 날, 아니면 start 와 같음
    start_time TEXT,               -- HH:MM 또는 NULL(종일)
    category   TEXT,               -- 학사 | 시험 | 행사 | 휴업 | 기타
    memo       TEXT,
    source     TEXT DEFAULT 'manual',   -- manual | ics
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS memos (
    memo_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT NOT NULL,      -- YYYY-MM-DD
    text       TEXT NOT NULL,
    created_at TEXT
);
"""


class State:
    def __init__(self, path: Optional[Path] = None):
        config.ensure_dirs()
        self.path = Path(path or config.STATE_PATH)
        self.con = sqlite3.connect(str(self.path))
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        self._migrate()
        self.con.commit()

    def _migrate(self) -> None:
        """예전 버전 DB 에 없는 칸을 조용히 덧붙인다."""
        for table, col, decl in (("messages", "source", "TEXT DEFAULT 'brity'"),
                                 ("tasks", "source", "TEXT DEFAULT 'brity'"),
                                 ("tasks", "done_at", "TEXT"),
                                 ("tasks", "kind", "TEXT DEFAULT 'mine'"),
                                 ("tasks", "short_title", "TEXT")):
            try:
                cols = {r[1] for r in self.con.execute(f"PRAGMA table_info({table})")}
                if col not in cols:
                    self.con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except Exception:
                pass

    # ---------- meta ----------
    def get_meta(self, key: str, default=None):
        r = self.con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_meta(self, key: str, value: str) -> None:
        self.con.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        self.con.commit()

    @property
    def last_run_at(self) -> Optional[datetime]:
        v = self.get_meta("last_run_at")
        return datetime.fromisoformat(v) if v else None

    def window_start(self, lookback_days: int) -> datetime:
        """이번 실행이 수집해야 할 시작 시점."""
        lr = self.last_run_at
        if lr:
            return lr
        return datetime.now() - timedelta(days=lookback_days)

    def mark_run_success(self, when: Optional[datetime] = None) -> None:
        self.set_meta("last_run_at", (when or datetime.now()).isoformat(timespec="seconds"))

    # ---------- messages ----------
    def known_list_keys(self) -> set:
        return {r["list_key"] for r in self.con.execute(
            "SELECT list_key FROM messages WHERE list_key IS NOT NULL")}

    def known_source_keys(self, source: str) -> set:
        """특정 메신저에서 이미 수집한 쪽지 키."""
        return {r["msg_id"] for r in self.con.execute(
            "SELECT msg_id FROM messages WHERE source=?", (source,))}

    def has_msg(self, msg_id: str) -> bool:
        return self.con.execute(
            "SELECT 1 FROM messages WHERE msg_id=?", (msg_id,)).fetchone() is not None

    def goe_list_order(self) -> list:
        """
        GOE 쪽지함에 지금 보일 순서(맨 위부터)를 되살린다.

        GOE 목록은 직접 그리기라 읽을 수 없지만, 순서는 계산할 수 있다.

          · 한 번의 수집은 목록 맨 위에서부터 아래로 훑는다
            → 같은 회차 안에서는 '저장한 순서 = 목록 순서'
          · 새 쪽지는 항상 위에 쌓인다
            → 나중 회차가 앞선 회차보다 위

        회차는 processed_at(저장 시각)이 붙어 있는 덩어리로 가른다.
        저장에 몇 초 걸리기도 하므로 2분 이내면 같은 회차로 본다.

        반환: msg_id 목록. 앞에 있을수록 목록 위쪽(= 최신).
        """
        rows = [dict(r) for r in self.con.execute(
            "SELECT rowid AS rid, msg_id, processed_at FROM messages "
            "WHERE source='goe' ORDER BY rowid ASC")]
        if not rows:
            return []

        def when(r):
            try:
                return datetime.fromisoformat(r["processed_at"])
            except Exception:
                return None

        runs, cur, prev = [], [], None
        for r in rows:
            t = when(r)
            if cur and (t is None or prev is None
                        or (t - prev).total_seconds() > 120):
                runs.append(cur)
                cur = []
            cur.append(r["msg_id"])
            prev = t or prev
        if cur:
            runs.append(cur)

        out = []
        for run in reversed(runs):      # 나중 회차가 위
            out.extend(run)             # 회차 안에서는 저장 순서 그대로
        return out

    def upsert_message(self, m: dict) -> None:
        self.con.execute(
            """INSERT INTO messages
               (msg_id,source,list_key,thread_key,subject,sender,sender_org,received_at,
                body_latest,body_raw,attachments,processed_at)
               VALUES(:msg_id,:source,:list_key,:thread_key,:subject,:sender,:sender_org,
                      :received_at,:body_latest,:body_raw,:attachments,:processed_at)
               ON CONFLICT(msg_id) DO UPDATE SET
                  body_latest=excluded.body_latest,
                  body_raw=excluded.body_raw,
                  processed_at=excluded.processed_at""",
            m,
        )
        self.con.commit()

    # ---------- tasks ----------
    def add_task(self, t: dict) -> int:
        cur = self.con.execute(
            """INSERT INTO tasks
               (msg_id,source,thread_key,title,detail,due_at,due_kind,requester,
                category,confidence,status,warn,created_at)
               VALUES(:msg_id,:source,:thread_key,:title,:detail,:due_at,:due_kind,
                      :requester,:category,:confidence,:status,:warn,:created_at)""",
            t,
        )
        self.con.commit()
        return int(cur.lastrowid)

    def find_open_task_in_thread(self, thread_key: str) -> Optional[sqlite3.Row]:
        return self.con.execute(
            "SELECT * FROM tasks WHERE thread_key=? AND status IN ('pending','approved') "
            "ORDER BY task_id DESC LIMIT 1",
            (thread_key,),
        ).fetchone()

    def update_task(self, task_id: int, **fields) -> None:
        if not fields:
            return
        sets = ",".join(f"{k}=?" for k in fields)
        self.con.execute(f"UPDATE tasks SET {sets} WHERE task_id=?",
                         (*fields.values(), task_id))
        self.con.commit()

    def open_tasks(self) -> list:
        """아직 끝내지 않은 할 일 전부 (완료·무시 제외). 패널이 쓰는 목록."""
        return list(self.con.execute(
            "SELECT * FROM tasks WHERE status IN ('pending','approved') "
            "ORDER BY CASE WHEN due_at IS NULL THEN 1 ELSE 0 END, due_at"))

    def complete_task(self, task_id: int) -> None:
        self.update_task(task_id, status="done",
                         done_at=datetime.now().isoformat(timespec="seconds"))

    def undo_complete(self, task_id: int) -> None:
        self.update_task(task_id, status="pending", done_at=None)

    def recently_done(self, limit: int = 20) -> list:
        return list(self.con.execute(
            "SELECT * FROM tasks WHERE status='done' "
            "ORDER BY done_at DESC LIMIT ?", (limit,)))

    def pending_tasks(self) -> list:
        return list(self.con.execute(
            "SELECT * FROM tasks WHERE status='pending' ORDER BY "
            "CASE WHEN due_at IS NULL THEN 1 ELSE 0 END, due_at"))

    def tasks_due_between(self, start: str, end: str) -> list:
        return list(self.con.execute(
            "SELECT * FROM tasks WHERE status IN ('approved','pending') "
            "AND due_at BETWEEN ? AND ? ORDER BY due_at", (start, end)))

    # ---------- 학사일정 ----------
    def add_school_event(self, title, start_date, end_date=None,
                         start_time=None, category="학사", memo="",
                         source="manual") -> int:
        cur = self.con.execute(
            """INSERT INTO school_events
               (title,start_date,end_date,start_time,category,memo,source,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (title, start_date, end_date or start_date, start_time, category,
             memo, source, datetime.now().isoformat(timespec="seconds")))
        self.con.commit()
        return int(cur.lastrowid)

    def school_events_between(self, start: str, end: str) -> list:
        """기간에 걸치는 학사일정 (여러 날짜 일정 포함)."""
        return list(self.con.execute(
            "SELECT * FROM school_events "
            "WHERE start_date <= ? AND end_date >= ? "
            "ORDER BY start_date, COALESCE(start_time,'00:00')",
            (end, start)))

    def delete_school_event(self, event_id: int) -> None:
        self.con.execute("DELETE FROM school_events WHERE event_id=?", (event_id,))
        self.con.commit()

    # ---- 날짜 메모 (달력에서 직접 적는 것) ----
    def add_memo(self, day: str, text: str) -> int:
        cur = self.con.execute(
            "INSERT INTO memos (day, text, created_at) VALUES (?,?,?)",
            (day, text, datetime.now().isoformat(timespec="seconds")))
        self.con.commit()
        return int(cur.lastrowid)

    def memos_between(self, start: str, end: str) -> list:
        return list(self.con.execute(
            "SELECT * FROM memos WHERE day BETWEEN ? AND ? "
            "ORDER BY day, memo_id", (start, end)))

    def delete_memo(self, memo_id: int) -> None:
        self.con.execute("DELETE FROM memos WHERE memo_id=?", (memo_id,))
        self.con.commit()

    def school_event_exists(self, title: str, start_date: str) -> bool:
        return self.con.execute(
            "SELECT 1 FROM school_events WHERE title=? AND start_date=? LIMIT 1",
            (title, start_date)).fetchone() is not None

    def tasks_between(self, start: str, end: str) -> list:
        """달력에 뿌릴 할 일 (완료·무시 제외)."""
        return list(self.con.execute(
            """SELECT t.*, m.source AS src_from, m.subject AS src_subject,
                      m.sender AS src_sender
               FROM tasks t LEFT JOIN messages m ON t.msg_id = m.msg_id
               WHERE t.status IN ('pending','approved')
                 AND t.due_at IS NOT NULL
                 AND substr(t.due_at,1,10) BETWEEN ? AND ?
               ORDER BY t.due_at""", (start, end)))

    # ---------- calendar ----------
    def link_event(self, task_id: int, provider: str, event_id: str, due_at: str) -> None:
        self.con.execute(
            """INSERT INTO calendar_links(task_id,provider,event_id,synced_at,last_due_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(task_id) DO UPDATE SET
                 provider=excluded.provider, event_id=excluded.event_id,
                 synced_at=excluded.synced_at, last_due_at=excluded.last_due_at""",
            (task_id, provider, event_id, datetime.now().isoformat(timespec="seconds"), due_at),
        )
        self.con.commit()

    def get_link(self, task_id: int) -> Optional[sqlite3.Row]:
        return self.con.execute(
            "SELECT * FROM calendar_links WHERE task_id=?", (task_id,)).fetchone()

    # ---------- runs ----------
    def start_run(self, trigger: str, window_from: str) -> int:
        cur = self.con.execute(
            "INSERT INTO runs(started_at,trigger,window_from,status) VALUES(?,?,?,'running')",
            (datetime.now().isoformat(timespec="seconds"), trigger, window_from),
        )
        self.con.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, **counts) -> None:
        self.con.execute(
            "UPDATE runs SET finished_at=?, status=?, collected=?, extracted=?, "
            "synced=?, error=? WHERE run_id=?",
            (datetime.now().isoformat(timespec="seconds"), status,
             counts.get("collected", 0), counts.get("extracted", 0),
             counts.get("synced", 0), counts.get("error"), run_id),
        )
        self.con.commit()

    def ran_successfully_within(self, minutes: int) -> bool:
        """
        최근 몇 분 안에 성공 실행이 있었는지.

        하루 두 번(아침·점심) 실행하므로 '오늘 이미 했나'로 막으면
        점심 실행이 아침 실행에 막혀 버린다. 시간 간격으로만 거른다.
        (보충 실행이 겹쳐 두 번 도는 것을 막는 용도)
        """
        cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat(
            timespec="seconds")
        return self.con.execute(
            "SELECT 1 FROM runs WHERE status='ok' AND started_at >= ? LIMIT 1",
            (cutoff,)).fetchone() is not None

    def ran_successfully_today(self) -> bool:
        today = datetime.now().date().isoformat()
        r = self.con.execute(
            "SELECT 1 FROM runs WHERE status='ok' AND date(started_at)=? LIMIT 1",
            (today,)).fetchone()
        return r is not None

    def days_since_last_success(self) -> Optional[int]:
        lr = self.last_run_at
        return (datetime.now() - lr).days if lr else None

    def close(self) -> None:
        try:
            self.con.close()
        except Exception:
            pass
