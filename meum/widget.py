# -*- coding: utf-8 -*-
"""
바탕화면 옆에 붙는 할 일 패널.

'목록'이 아니라 '언제 무엇을 해야 하는가'로 보여준다.

  · 회색 바탕 위에 흰 카드 — 카드 왼쪽 색 띠가 급한 정도를 나타낸다
      진빨강=기한 지남 · 빨강=오늘 · 주황=내일 · 호박=이번 주 · 파랑=그 뒤
  · 날짜 머리글에는 D-day 배지, 패널 머리에는 지남/오늘 개수 배지
  · 네모(☐) 클릭 = 완료, 두 번 클릭 = 원래 쪽지 열기

로그인하면 자동으로 뜬다(설치 시 시작 프로그램 등록). 이미 떠 있으면 중복 실행하지 않는다.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import font as tkfont
from typing import Dict, List, Optional, Tuple

import calendar as pycal

from . import APP_NAME, APP_TAGLINE_SHORT, WINDOW_PANEL, config
from .state import State

WINDOW_TITLE = WINDOW_PANEL

# ---- 색 (디자인 체계) ----
PAGE_BG = "#eef1f6"      # 패널 바탕 (옅은 회색)
CARD_BG = "#ffffff"      # 카드
CARD_HOVER = "#f4f7fb"   # 카드에 마우스를 올렸을 때
HEAD_BG = "#0f172a"      # 머리말 (짙은 남색)
HEAD_SUB = "#94a3b8"
HEAD_FG = "#f8fafc"
FG = "#0f172a"
MUTED = "#64748b"
FAINT = "#94a3b8"
LINE = "#dde3ec"

OVERDUE = "#991b1b"      # 기한 지남
TODAY_C = "#dc2626"      # 오늘
TOMORROW = "#ea580c"     # 내일
SOON = "#b45309"         # 이번 주
LATER = "#2563eb"        # 그 이후
NONE_C = "#64748b"       # 기한 없음
MINE_C = "#0f766e"       # 내 할 일 (달력 점)
NOTICE_C = "#7c3aed"     # 알아둘 일
SCHOOL_C = "#b45309"     # 학사일정
SCHOOL_BG = "#fff7ed"    # 학사일정 카드 바탕

SAT_C = "#2563eb"
SUN_C = "#dc2626"
CELL_TODAY = "#dbeafe"
CELL_PICK = "#2563eb"

ACCENT = "#2563eb"
ACCENT_DARK = "#1e40af"

# 예약 정리가 창 없이 돌므로, 결과가 패널에 곧 보여야 한다 → 1분마다 다시 읽는다
REFRESH_MS = 60 * 1000
WEEKDAY = "월화수목금토일"


def _dpi():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _work_area():
    try:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return 0, 0, 1920, 1040


def _fmt_day(d: date, today: date) -> Tuple[str, str, str]:
    """(머리글, D-day 표시, 색) 반환."""
    diff = (d - today).days
    label = f"{d.month}/{d.day} {WEEKDAY[d.weekday()]}"
    if diff < 0:
        return label, f"{-diff}일 지남", OVERDUE
    if diff == 0:
        return f"오늘 · {label}", "TODAY", TODAY_C
    if diff == 1:
        return f"내일 · {label}", "D-1", TOMORROW
    if diff <= 7:
        return label, f"D-{diff}", SOON
    return label, f"D-{diff}", LATER


def already_running() -> bool:
    """같은 제목의 패널이 이미 떠 있는지."""
    try:
        import win32gui
        found = []
        win32gui.EnumWindows(
            lambda h, _: (found.append(h)
                          if win32gui.IsWindowVisible(h)
                          and win32gui.GetWindowText(h) == WINDOW_TITLE
                          else None, True)[-1], None)
        return bool(found)
    except Exception:
        return False


class Widget:
    def __init__(self):
        _dpi()
        self.cfg = config.load()
        self.view = self.cfg.get("widget_view", "mine")   # mine | date | note
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.configure(bg=PAGE_BG)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", bool(self.cfg.get("widget_always_on_top", False)))

        self.f = {
            "brand": tkfont.Font(family="맑은 고딕", size=9, weight="bold"),
            "head": tkfont.Font(family="맑은 고딕", size=12, weight="bold"),
            "headsub": tkfont.Font(family="맑은 고딕", size=8),
            "pill": tkfont.Font(family="맑은 고딕", size=8, weight="bold"),
            "tab": tkfont.Font(family="맑은 고딕", size=9),
            "tabsel": tkfont.Font(family="맑은 고딕", size=9, weight="bold"),
            "day": tkfont.Font(family="맑은 고딕", size=10, weight="bold"),
            "item": tkfont.Font(family="맑은 고딕", size=10),
            "time": tkfont.Font(family="맑은 고딕", size=10, weight="bold"),
            "src": tkfont.Font(family="맑은 고딕", size=8),
            "btn": tkfont.Font(family="맑은 고딕", size=9, weight="bold"),
            "small": tkfont.Font(family="맑은 고딕", size=8),
            "cal": tkfont.Font(family="맑은 고딕", size=9),
            "calb": tkfont.Font(family="맑은 고딕", size=9, weight="bold"),
            "check": tkfont.Font(family="맑은 고딕", size=12),
        }
        today = date.today()
        self.cal_y, self.cal_m = today.year, today.month
        self.day_filter = None
        self._drag = None
        self._alerted = {}            # 알람 중복 방지: {task_id: {"stages", "last"}}
        self._alarm_win = None
        self._build()
        self._place()
        self.refresh()
        self.root.after(8000, self._check_alarms)   # 켜지고 잠시 뒤 첫 점검
        self.root.after(REFRESH_MS, self._tick)

    # ------------------------------------------------------------------
    # 뼈대
    # ------------------------------------------------------------------
    def _build(self):
        # ── 머리말: 짙은 남색 띠, 제목 + 개수 배지 ──
        head = tk.Frame(self.root, bg=HEAD_BG, height=66)
        head.pack(fill="x")
        head.pack_propagate(False)

        # 윗줄: 이름 + 오늘 날짜 (왼쪽) · 창 단추 (오른쪽)
        row1 = tk.Frame(head, bg=HEAD_BG)
        row1.pack(fill="x", padx=(14, 10), pady=(8, 0))
        self.brand_lbl = tk.Label(row1, text=APP_NAME, font=self.f["brand"],
                                  bg=HEAD_BG, fg="#7dd3fc")
        self.brand_lbl.pack(side="left")
        self.date_lbl = tk.Label(row1, text="", font=self.f["headsub"],
                                 bg=HEAD_BG, fg=HEAD_SUB)
        self.date_lbl.pack(side="left", padx=(8, 0))

        btns = tk.Frame(row1, bg=HEAD_BG)
        btns.pack(side="right")
        for txt, cmd, tip in (("✕", self.root.destroy, None),
                              ("📌", self._toggle_pin, None),
                              ("↻", self.refresh, None),
                              ("📅", self._open_calendar, None)):
            b = tk.Label(btns, text=txt, font=self.f["tab"], bg=HEAD_BG,
                         fg=HEAD_SUB, cursor="hand2")
            b.pack(side="right", padx=5)
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=b: w.configure(fg=HEAD_FG))
            b.bind("<Leave>", lambda e, w=b: w.configure(fg=HEAD_SUB))

        # 아랫줄: 할 일 개수와 배지를 같은 줄에 나란히 (겹치지 않게)
        row2 = tk.Frame(head, bg=HEAD_BG)
        row2.pack(fill="x", padx=(14, 10), pady=(2, 0))
        self.title_lbl = tk.Label(row2, text="할 일", font=self.f["head"],
                                  bg=HEAD_BG, fg=HEAD_FG)
        self.title_lbl.pack(side="left")
        self.pills = tk.Frame(row2, bg=HEAD_BG)
        self.pills.pack(side="left", padx=(10, 0))

        for w in (head, row1, row2, self.title_lbl, self.date_lbl,
                  self.brand_lbl, self.pills):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)

        # ── 탭: 알약 모양 ──
        tabbar = tk.Frame(self.root, bg=PAGE_BG)
        tabbar.pack(fill="x", padx=10, pady=(8, 0))
        self.tab_btns = {}
        for key, label in (("mine", "내 할 일"), ("date", "전체"), ("note", "쪽지별")):
            b = tk.Label(tabbar, text=label, font=self.f["tab"], bg=PAGE_BG,
                         fg=MUTED, cursor="hand2", padx=11, pady=4)
            b.pack(side="left", padx=(0, 4))
            b.bind("<Button-1>", lambda e, k=key: self._set_view(k))
            self.tab_btns[key] = b

        # ── 작은 달력 카드 ──
        calcard = tk.Frame(self.root, bg=CARD_BG,
                           highlightbackground=LINE, highlightthickness=1)
        calcard.pack(fill="x", padx=10, pady=(8, 0))
        self.mini_head = tk.Frame(calcard, bg=CARD_BG)
        self.mini_head.pack(fill="x", padx=10, pady=(7, 0))
        self.mini_grid = tk.Frame(calcard, bg=CARD_BG)
        self.mini_grid.pack(fill="x", padx=6, pady=(2, 7))

        tk.Label(self.root, text="☐ 누르면 완료  ·  카드를 두 번 누르면 원래 쪽지",
                 font=self.f["small"], bg=PAGE_BG, fg=FAINT).pack(anchor="w",
                                                                  padx=14, pady=(6, 0))

        # ── 본문 스크롤 ──
        wrap = tk.Frame(self.root, bg=PAGE_BG)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=PAGE_BG, highlightthickness=0)
        vsb = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=PAGE_BG)
        self.body.bind("<Configure>",
                       lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))

        # ── 발치 ──
        foot = tk.Frame(self.root, bg=CARD_BG)
        foot.pack(fill="x", side="bottom")
        tk.Frame(foot, bg=LINE, height=1).pack(fill="x")
        inner = tk.Frame(foot, bg=CARD_BG)
        inner.pack(fill="x", padx=10, pady=8)
        self.run_btn = tk.Button(inner, text="⟳  지금 쪽지 정리", font=self.f["btn"],
                                 relief="flat", bg=ACCENT, fg="white",
                                 activebackground=ACCENT_DARK, activeforeground="white",
                                 cursor="hand2", padx=12, pady=4,
                                 command=self._run_now)
        self.run_btn.pack(side="left")
        self.undo_btn = tk.Label(inner, text="", font=self.f["small"], bg=CARD_BG,
                                 fg=ACCENT, cursor="hand2")
        self.undo_btn.pack(side="left", padx=(10, 0))
        self.undo_btn.bind("<Button-1>", lambda e: self._undo())
        self.status = tk.Label(inner, text="", font=self.f["small"], bg=CARD_BG, fg=FAINT)
        self.status.pack(side="right")

        # 이 프로그램이 왜 있는지 — 늘 보이는 자리에 한 줄
        tk.Label(foot, text=f"{APP_NAME} · {APP_TAGLINE_SHORT}",
                 font=self.f["small"], bg=CARD_BG, fg=FAINT)            .pack(anchor="w", padx=12, pady=(0, 7))
        self._last_done = None
        self._gs_note = ""
        self._stamp = ""

    def _place(self):
        l, t, r, b = _work_area()
        w = int(self.cfg.get("widget_width", 380))
        x, y = self.cfg.get("widget_x"), self.cfg.get("widget_y")
        h = b - t
        if x is None or y is None:
            x, y = r - w, t
        self.root.geometry(f"{w}x{h}+{int(x)}+{int(y)}")

    def _set_view(self, key: str):
        # 패널은 자기가 바꾼 항목만 저장한다.
        # 통째로 저장하면(save) 켜질 때 읽어둔 낡은 사본이 그 사이 마법사에서
        # 바꾼 점검 시각 등을 되돌려 버린다.
        self.view = key
        self.cfg = config.update(widget_view=key)
        self.refresh()

    # ---- 창 끌기 ----
    def _drag_start(self, e):
        self._drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag_move(self, e):
        if not self._drag:
            return
        sx, sy, ox, oy = self._drag
        self.root.geometry(f"+{ox + e.x_root - sx}+{oy + e.y_root - sy}")

    def _drag_end(self, e):
        self._drag = None
        self.cfg = config.update(widget_x=self.root.winfo_x(),
                                 widget_y=self.root.winfo_y())

    def _toggle_pin(self):
        v = not bool(self.cfg.get("widget_always_on_top", False))
        self.cfg = config.update(widget_always_on_top=v)
        self.root.attributes("-topmost", v)
        self.status.configure(text="항상 위 켬" if v else "항상 위 끔")

    # ------------------------------------------------------------------
    def _tick(self):
        self.refresh()
        self._sync_google()
        self._check_alarms()
        self.root.after(REFRESH_MS, self._tick)

    # ------------------------------------------------------------------
    # 오늘 마감 알람 — 깜빡함 방지
    # ------------------------------------------------------------------
    def _check_alarms(self):
        """
        1분마다 돌며 알람 창을 띄운다.

          · 마감 1시간 전(설정 가능)   → 한 번
          · 마감 시각이 지났는데 미완료 → 알리고, 이후 2시간마다 반복
          · 어제까지 마감이었는데 남음  → 2시간마다 반복 (깜빡한 것)

        완료 체크하면 그 항목의 알람은 멈춘다.
        """
        if not self.cfg.get("alarm_enabled", True):
            return
        try:
            rows, _, _ = self._load()
        except Exception:
            return

        from datetime import time as _t
        now = datetime.now()
        today = now.date()
        before = int(self.cfg.get("remind_before_min", 60))
        repeat = int(self.cfg.get("remind_repeat_min", 120))

        fire_list = []
        for r in rows:
            da = r.get("due_at")
            if not da:
                continue
            d = date.fromisoformat(da[:10])
            if d > today:
                continue
            dt = (datetime.fromisoformat(da) if "T" in da
                  else datetime.combine(d, _t(17, 0)))
            tid = r["task_id"]
            st = self._alerted.setdefault(tid, {"stages": set(), "last": None})

            def elapsed():
                return (st["last"] is None
                        or (now - st["last"]).total_seconds() >= repeat * 60)

            stage = None
            if d < today:
                if elapsed():
                    stage = "지남"
            elif now >= dt:
                if "due" not in st["stages"] or elapsed():
                    stage = "마감"
                    st["stages"].add("due")
            elif now >= dt - timedelta(minutes=before):
                if "pre" not in st["stages"]:
                    stage = f"{before}분 전"
                    st["stages"].add("pre")

            if stage:
                st["last"] = now
                fire_list.append((stage, r, dt))

        if fire_list:
            self._show_alarm(fire_list)

    def _show_alarm(self, items):
        """빨간 머리말의 작은 알람 창. 소리와 함께 화면 앞에 뜬다."""
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass

        if self._alarm_win is not None:
            try:
                self._alarm_win.destroy()
            except Exception:
                pass

        win = tk.Toplevel(self.root)
        self._alarm_win = win
        win.title(f"{APP_NAME} 알림")
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=CARD_BG, highlightbackground=TODAY_C,
                      highlightthickness=2)

        head = tk.Frame(win, bg=TODAY_C)
        head.pack(fill="x")
        tk.Label(head, text=f"🔔 오늘 처리할 일 {len(items)}건",
                 font=self.f["head"], bg=TODAY_C, fg="white")\
            .pack(side="left", padx=14, pady=8)

        body = tk.Frame(win, bg=CARD_BG)
        body.pack(fill="both", padx=14, pady=(10, 4))
        for stage, r, dt in items[:6]:
            line = tk.Frame(body, bg=CARD_BG)
            line.pack(fill="x", pady=3)
            tk.Label(line, text=stage, font=self.f["pill"], bg=TODAY_C,
                     fg="white", padx=6, pady=1).pack(side="left")
            if dt.date() < datetime.now().date():
                when = f"{dt.month}/{dt.day}"       # 깜빡한 것은 날짜로
            else:
                when = dt.strftime("%H:%M")
            tk.Label(line, text=when, font=self.f["time"], bg=CARD_BG,
                     fg=TODAY_C).pack(side="left", padx=(8, 6))
            tk.Label(line, text=(r.get("short_title") or r["title"])[:34],
                     font=self.f["item"], bg=CARD_BG, fg=FG).pack(side="left")
        if len(items) > 6:
            tk.Label(body, text=f"… 외 {len(items) - 6}건", font=self.f["small"],
                     bg=CARD_BG, fg=MUTED).pack(anchor="w")

        btns = tk.Frame(win, bg=CARD_BG)
        btns.pack(fill="x", padx=14, pady=(6, 12))

        def close(_=None):
            try:
                win.destroy()
            except Exception:
                pass
            self._alarm_win = None

        def show_panel(_=None):
            close()
            try:
                self.root.attributes("-topmost", True)
                self.root.lift()
                if not self.cfg.get("widget_always_on_top", False):
                    self.root.after(3000,
                                    lambda: self.root.attributes("-topmost", False))
            except Exception:
                pass

        tk.Button(btns, text="패널 보기", font=self.f["btn"], relief="flat",
                  bg=TODAY_C, fg="white", activebackground="#991b1b",
                  activeforeground="white", padx=12, pady=3,
                  command=show_panel).pack(side="left")
        tk.Button(btns, text="확인", font=self.f["btn"], relief="flat",
                  padx=14, pady=3, command=close).pack(side="right")

        # 패널 왼쪽에 붙여서, 화면 한가운데를 가리지 않게 한다
        win.update_idletasks()
        w, h = max(330, win.winfo_reqwidth()), win.winfo_reqheight()
        px, py = self.root.winfo_x(), self.root.winfo_y()
        win.geometry(f"{w}x{h}+{max(0, px - w - 12)}+{py + 60}")
        win.after(60000, close)      # 1분 뒤 스스로 닫힘 (다음 반복 때 다시 뜸)

    # ---- 구글 캘린더 (선택 기능) ----
    def _sync_google(self):
        try:
            from . import gsync
        except Exception:
            return
        if not (gsync.enabled(self.cfg) and gsync.connected()):
            return

        def after(res):
            self._gs_note = res.summary()
            try:
                self.root.after(0, self._paint_status)
            except Exception:
                pass

        gsync.sync_in_background(self.cfg, after)

    def _paint_status(self):
        bits = [b for b in (self._stamp, self._gs_note) if b]
        self.status.configure(text="  ·  ".join(bits))

    # ---- 완료 되돌리기 ----
    def _show_undo(self, label: str):
        self.undo_btn.configure(text=f"↺ 되돌리기 ({label[:12]})")
        self.root.after(15000, lambda: self.undo_btn.configure(text=""))

    def _undo(self):
        if not self._last_done:
            return
        try:
            st = State()
            st.undo_complete(self._last_done)
            st.close()
        except Exception:
            pass
        self._last_done = None
        self.undo_btn.configure(text="")
        self.refresh()
        self._sync_google()

    # ------------------------------------------------------------------
    def _load(self):
        st = State()
        rows = [dict(r) for r in st.con.execute("""
            SELECT t.*, m.subject AS src_subject, m.sender AS src_sender,
                   m.received_at AS src_received, m.source AS src_from
            FROM tasks t LEFT JOIN messages m ON t.msg_id = m.msg_id
            WHERE t.status IN ('approved','pending')
        """)]
        last = st.last_run_at
        y, m = self.cal_y, self.cal_m
        lo = date(y - (m == 1), 12 if m == 1 else m - 1, 1).isoformat()
        hi = date(y + (m == 12), 1 if m == 12 else m + 1, 28).isoformat()
        try:
            events = [dict(r) for r in st.school_events_between(lo, hi)]
        except Exception:
            events = []
        st.close()
        return rows, last, events

    # ------------------------------------------------------------------
    def refresh(self):
        for w in self.body.winfo_children():
            w.destroy()
        for k, b in self.tab_btns.items():
            if k == self.view:
                b.configure(bg=HEAD_BG, fg="white", font=self.f["tabsel"])
            else:
                b.configure(bg=PAGE_BG, fg=MUTED, font=self.f["tab"])

        try:
            rows, last, events = self._load()
        except Exception as e:
            tk.Label(self.body, text=f"목록을 읽지 못했습니다.\n{e}", font=self.f["item"],
                     bg=PAGE_BG, fg=MUTED, wraplength=300, justify="left").pack(pady=20)
            return

        today = date.today()
        overdue = sum(1 for r in rows
                      if r["due_at"] and date.fromisoformat(r["due_at"][:10]) < today)
        due_today = sum(1 for r in rows
                        if r["due_at"] and date.fromisoformat(r["due_at"][:10]) == today)
        mine_n = sum(1 for r in rows if (r.get("kind") or "mine") == "mine")

        self.title_lbl.configure(
            text=f"할 일 {mine_n}" if self.view != "date" else f"전체 {len(rows)}")
        self.date_lbl.configure(
            text=f"{today.month}월 {today.day}일 {WEEKDAY[today.weekday()]}요일")

        # 개수 배지
        for w in self.pills.winfo_children():
            w.destroy()
        for n, label, colr in ((overdue, "지남", OVERDUE), (due_today, "오늘", TODAY_C)):
            if n:
                tk.Label(self.pills, text=f"{label} {n}", font=self.f["pill"],
                         bg=colr, fg="white", padx=7, pady=1).pack(side="left",
                                                                   padx=(0, 5), pady=(3, 0))

        # 달력 점
        marks = {}
        for r in rows:
            if not r["due_at"]:
                continue
            dd = date.fromisoformat(r["due_at"][:10])
            if dd < today:
                col = OVERDUE
            elif dd == today:
                col = TODAY_C
            else:
                col = MINE_C if (r.get("kind") or "mine") == "mine" else NOTICE_C
            marks.setdefault(dd, set()).add(col)
        for e in events:
            try:
                s0 = date.fromisoformat(e["start_date"])
                s1 = date.fromisoformat(e["end_date"] or e["start_date"])
            except Exception:
                continue
            dd = s0
            while dd <= s1:
                marks.setdefault(dd, set()).add(SCHOOL_C)
                dd += timedelta(days=1)
        self._events = events
        self._paint_mini(marks)

        if self.day_filter:
            want = self.day_filter.isoformat()
            rows = [r for r in rows if (r["due_at"] or "")[:10] == want]
            self._events = [e for e in events
                            if e["start_date"] <= want <= (e["end_date"] or e["start_date"])]

        # ── 오늘 배너: 오늘 마감 + 깜빡한 것(지남)을 맨 위에 빨갛게 ──
        self._today_banner(rows)

        if not rows and not (self.day_filter and self._events):
            msg = ("고른 날에는 할 일이 없습니다." if self.day_filter
                   else "✓\n\n모두 정리되어 있습니다.\n'지금 쪽지 정리'로 새 쪽지를 확인하세요.")
            tk.Label(self.body, text=msg, font=self.f["item"],
                     bg=PAGE_BG, fg=MUTED, justify="center").pack(pady=36)
        elif self.view == "note":
            self._render_by_note(rows)
        else:
            shown = rows if self.view == "date" else [
                r for r in rows if (r.get("kind") or "mine") == "mine"]
            if not shown and not self._events:
                tk.Label(self.body,
                         text="✓\n\n처리할 일이 없습니다.\n'전체' 탭에 안내 사항이 있습니다.",
                         font=self.f["item"], bg=PAGE_BG, fg=MUTED,
                         justify="center").pack(pady=36)
            else:
                self._render_by_date(shown)

        self._stamp = f"{last:%m/%d %H:%M} 정리됨" if last else "아직 정리 안 함"
        self._paint_status()

    # ---- 오늘 배너 ----
    def _today_banner(self, rows: List[dict]):
        """
        '오늘 당장 뭘 해야 하나'를 목록 맨 위에 빨간 판으로 박아 둔다.
        지나간 마감(깜빡한 것)도 여기 함께 올라온다.
        """
        today = date.today()
        urgent = []
        for r in rows:
            if not r.get("due_at"):
                continue
            d = date.fromisoformat(r["due_at"][:10])
            if d <= today:
                urgent.append((d, r))
        if not urgent:
            return
        urgent.sort(key=lambda x: (x[0], x[1]["due_at"] or ""))

        outer = tk.Frame(self.body, bg=PAGE_BG)
        outer.pack(fill="x", padx=12, pady=(10, 2))
        card = tk.Frame(outer, bg=TODAY_C)
        card.pack(fill="x")

        n_over = sum(1 for d, _ in urgent if d < today)
        n_today = len(urgent) - n_over
        head_txt = "🔔 오늘 처리"
        bits = []
        if n_today:
            bits.append(f"오늘 {n_today}건")
        if n_over:
            bits.append(f"깜빡한 것 {n_over}건")
        tk.Label(card, text=f"{head_txt}  ·  {' · '.join(bits)}",
                 font=self.f["day"], bg=TODAY_C, fg="white")\
            .pack(anchor="w", padx=12, pady=(8, 4))

        inner = tk.Frame(card, bg=TODAY_C)
        inner.pack(fill="x", padx=12, pady=(0, 9))
        for d, r in urgent[:5]:
            line = tk.Frame(inner, bg=TODAY_C, cursor="hand2")
            line.pack(fill="x", pady=1)
            due = r["due_at"] or ""
            when = due[11:16] if "T" in due else "종일"
            if d < today:
                when = f"{d.month}/{d.day}"
            box = tk.Label(line, text="☐", font=self.f["item"], bg=TODAY_C,
                           fg="#fecaca", cursor="hand2")
            box.pack(side="left")
            tk.Label(line, text=when, font=self.f["time"], bg=TODAY_C,
                     fg="#fecaca").pack(side="left", padx=(4, 6))
            tk.Label(line, text=(r.get("short_title") or r["title"])[:26],
                     font=self.f["item"], bg=TODAY_C, fg="white",
                     anchor="w").pack(side="left", fill="x", expand=True)

            def done(_=None, task=r):
                try:
                    st = State()
                    st.complete_task(task["task_id"])
                    st.close()
                except Exception:
                    pass
                self._last_done = task["task_id"]
                self._show_undo(task.get("short_title") or task["title"])
                self.refresh()
                self._sync_google()

            box.bind("<Button-1>", done)
            box.bind("<Enter>", lambda e, b=box: b.configure(text="☑", fg="white"))
            box.bind("<Leave>", lambda e, b=box: b.configure(text="☐", fg="#fecaca"))
        if len(urgent) > 5:
            tk.Label(inner, text=f"… 외 {len(urgent) - 5}건 (아래 목록에)",
                     font=self.f["small"], bg=TODAY_C, fg="#fecaca")\
                .pack(anchor="w", pady=(2, 0))

    # ---- 날짜별 ----
    def _render_by_date(self, rows: List[dict]):
        today = date.today()
        by_day: Dict[Optional[date], List[dict]] = {}
        for r in rows:
            d = date.fromisoformat(r["due_at"][:10]) if r["due_at"] else None
            by_day.setdefault(d, []).append(r)

        sch: Dict[date, List[dict]] = {}
        for e in getattr(self, "_events", []):
            try:
                s0 = date.fromisoformat(e["start_date"])
                s1 = date.fromisoformat(e["end_date"] or e["start_date"])
            except Exception:
                continue
            dd = max(s0, today)
            while dd <= s1:
                sch.setdefault(dd, []).append(e)
                dd += timedelta(days=1)

        dated = sorted(set([d for d in by_day if d is not None]) | set(sch.keys()))
        for d in dated:
            label, dday, color = _fmt_day(d, today)
            self._day_header(label, dday, color)
            for e in sch.get(d, []):
                self._school_item(e)
            for r in sorted(by_day.get(d, []), key=lambda x: (x["due_at"] or "")):
                self._item(r, color, show_time=True)

        if None in by_day:
            self._day_header("기한 없음", f"{len(by_day[None])}", NONE_C)
            for r in by_day[None]:
                self._item(r, NONE_C, show_time=False)

    # ---- 쪽지별 ----
    def _render_by_note(self, rows: List[dict]):
        today = date.today()
        by_msg: Dict[str, List[dict]] = {}
        for r in rows:
            by_msg.setdefault(r["msg_id"] or "?", []).append(r)

        def first_due(items):
            ds = [i["due_at"] for i in items if i["due_at"]]
            return min(ds) if ds else "9999"

        for _, items in sorted(by_msg.items(), key=lambda kv: first_due(kv[1])):
            head = items[0]
            sender = head.get("src_sender") or (head.get("requester") or "").split("(")[0]
            subj = (head.get("src_subject") or "").strip()
            recv = head.get("src_received") or ""
            when = f"{recv[5:10].replace('-', '/')} 받음" if recv else ""
            self._day_header(sender or "보낸 사람 미상", when, LATER)
            if subj:
                tk.Label(self.body, text=subj[:46], font=self.f["src"], bg=PAGE_BG,
                         fg=FAINT, anchor="w", justify="left", wraplength=300)\
                    .pack(anchor="w", padx=16, pady=(0, 2))
            for r in sorted(items, key=lambda x: (x["due_at"] or "9999")):
                d = date.fromisoformat(r["due_at"][:10]) if r["due_at"] else None
                color = _fmt_day(d, today)[2] if d else NONE_C
                self._item(r, color, show_time=True, show_source=False)

    # ------------------------------------------------------------------
    # 그리기 조각
    # ------------------------------------------------------------------
    def _day_header(self, label: str, badge: str, color: str):
        fr = tk.Frame(self.body, bg=PAGE_BG)
        fr.pack(fill="x", padx=12, pady=(14, 5))
        tk.Label(fr, text=label, font=self.f["day"], bg=PAGE_BG, fg=color)\
            .pack(side="left")
        if badge:
            tk.Label(fr, text=badge, font=self.f["pill"], bg=color, fg="white",
                     padx=7, pady=1).pack(side="right")

    def _hover(self, widgets, on, off):
        def enter(_):
            for w in widgets:
                try:
                    w.configure(bg=on)
                except Exception:
                    pass

        def leave(_):
            for w in widgets:
                try:
                    w.configure(bg=off)
                except Exception:
                    pass

        for w in widgets:
            w.bind("<Enter>", enter, add="+")
            w.bind("<Leave>", leave, add="+")

    def _card(self, stripe_color: str, bg: str = CARD_BG):
        """왼쪽 색 띠가 있는 흰 카드. (card, content) 반환."""
        outer = tk.Frame(self.body, bg=PAGE_BG)
        outer.pack(fill="x", padx=12, pady=3)
        card = tk.Frame(outer, bg=bg, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x")
        stripe = tk.Frame(card, bg=stripe_color, width=4)
        stripe.pack(side="left", fill="y")
        content = tk.Frame(card, bg=bg)
        content.pack(side="left", fill="x", expand=True, padx=(8, 8), pady=6)
        return card, content

    def _item(self, r: dict, color: str, show_time: bool = True,
              show_source: bool = True):
        pending = r.get("status") == "pending"
        stripe = FAINT if pending else color
        card, content = self._card(stripe)

        row = tk.Frame(content, bg=CARD_BG)
        row.pack(fill="x")

        box = tk.Label(row, text="☐", font=self.f["check"], bg=CARD_BG,
                       fg=(FAINT if pending else color), cursor="hand2")
        box.pack(side="left", anchor="n", padx=(0, 7))

        right = tk.Frame(row, bg=CARD_BG)
        right.pack(side="left", fill="x", expand=True)

        due = r["due_at"] or ""
        tline = tk.Frame(right, bg=CARD_BG)
        tline.pack(fill="x")
        if show_time and "T" in due:
            tk.Label(tline, text=due[11:16], font=self.f["time"],
                     bg=CARD_BG, fg=color).pack(side="left", padx=(0, 7))
        elif show_time and due:
            tk.Label(tline, text="종일", font=self.f["time"],
                     bg=CARD_BG, fg=color).pack(side="left", padx=(0, 7))

        avail = max(150, int(self.cfg.get("widget_width", 380)) - 150)
        shown_title = (r.get("short_title") or r["title"])[:120]
        title = tk.Label(tline, text=shown_title, font=self.f["item"], bg=CARD_BG,
                         fg=FG, anchor="w", justify="left", wraplength=avail)
        title.pack(side="left", fill="x", expand=True)
        if pending:
            tk.Label(tline, text="미확정", font=self.f["pill"], bg="#e2e8f0",
                     fg=MUTED, padx=5, pady=1).pack(side="right", anchor="n",
                                                    padx=(4, 0))

        hover_targets = [card, content, row, right, tline, title]

        if show_source:
            sender = r.get("src_sender") or (r.get("requester") or "").split("(")[0]
            subj = " ".join((r.get("src_subject") or "").split())
            parts = []
            origin = (r.get("src_from") or "").strip()
            if origin == "goe":
                parts.append("GOE")
            if sender:
                parts.append(sender)
            if subj:
                parts.append(subj[:14] + ("…" if len(subj) > 14 else ""))
            if parts:
                src = tk.Label(right, text="↳ " + " · ".join(parts),
                               font=self.f["src"], bg=CARD_BG, fg=FAINT, anchor="w")
                src.pack(anchor="w", pady=(2, 0))
                hover_targets.append(src)

        self._hover(hover_targets, CARD_HOVER, CARD_BG)

        def done(_=None):
            try:
                st = State()
                st.complete_task(r["task_id"])
                st.close()
            except Exception:
                pass
            self._last_done = r["task_id"]
            self._show_undo(r.get("short_title") or r["title"])
            self.refresh()
            self._sync_google()

        def reopen(_=None):
            self._open_original(r)

        box.bind("<Button-1>", done)
        box.bind("<Enter>", lambda e: box.configure(text="☑"), add="+")
        box.bind("<Leave>", lambda e: box.configure(text="☐"), add="+")
        for w in hover_targets:
            w.bind("<Double-Button-1>", reopen)

    def _school_item(self, e: dict):
        card, content = self._card(SCHOOL_C, bg=SCHOOL_BG)
        line = tk.Frame(content, bg=SCHOOL_BG)
        line.pack(fill="x")
        tk.Label(line, text="학사", font=self.f["pill"], bg=SCHOOL_C, fg="white",
                 padx=5, pady=1).pack(side="left", padx=(0, 7))
        if e.get("start_time"):
            tk.Label(line, text=e["start_time"], font=self.f["time"], bg=SCHOOL_BG,
                     fg=SCHOOL_C).pack(side="left", padx=(0, 6))
        tk.Label(line, text=(e.get("title") or "")[:40], font=self.f["item"],
                 bg=SCHOOL_BG, fg=FG, anchor="w", justify="left",
                 wraplength=max(150, int(self.cfg.get("widget_width", 380)) - 150))\
            .pack(side="left", fill="x", expand=True)

    # ------------------------------------------------------------------
    # 작은 달력
    # ------------------------------------------------------------------
    def _paint_mini(self, marks):
        for w in self.mini_head.winfo_children():
            w.destroy()
        for w in self.mini_grid.winfo_children():
            w.destroy()

        title = tk.Label(self.mini_head, text=f"{self.cal_y}년 {self.cal_m}월",
                         font=self.f["calb"], bg=CARD_BG, fg=FG, cursor="hand2")
        title.pack(side="left")
        title.bind("<Button-1>", lambda e: self._open_calendar())

        nxt = tk.Label(self.mini_head, text=" › ", font=self.f["calb"], bg=CARD_BG,
                       fg=MUTED, cursor="hand2")
        nxt.pack(side="right")
        nxt.bind("<Button-1>", lambda e: self._shift_month(1))
        prev = tk.Label(self.mini_head, text=" ‹ ", font=self.f["calb"], bg=CARD_BG,
                        fg=MUTED, cursor="hand2")
        prev.pack(side="right")
        prev.bind("<Button-1>", lambda e: self._shift_month(-1))

        if self.day_filter:
            clr = tk.Label(self.mini_head, text="전체 보기", font=self.f["small"],
                           bg="#e0e7ff", fg=ACCENT_DARK, cursor="hand2",
                           padx=6, pady=1)
            clr.pack(side="right", padx=(0, 8))
            clr.bind("<Button-1>", lambda e: self._pick_day(None))

        for i in range(7):
            self.mini_grid.grid_columnconfigure(i, weight=1, uniform="c")
        for i, wk in enumerate("월화수목금토일"):
            fg = SUN_C if i == 6 else (SAT_C if i == 5 else FAINT)
            tk.Label(self.mini_grid, text=wk, font=self.f["small"], bg=CARD_BG,
                     fg=fg).grid(row=0, column=i, pady=(2, 1))

        first = date(self.cal_y, self.cal_m, 1)
        last = date(self.cal_y, self.cal_m, pycal.monthrange(self.cal_y, self.cal_m)[1])
        start = first - timedelta(days=first.weekday())
        rows = ((last + timedelta(days=(6 - last.weekday()))) - start).days // 7 + 1
        today = date.today()

        d = start
        for r in range(1, rows + 1):
            for c in range(7):
                self._mini_cell(r, c, d, first, last, today, marks.get(d, set()))
                d += timedelta(days=1)

    def _mini_cell(self, r, c, d, first, last, today, colors):
        in_month = first <= d <= last
        bg = CARD_BG
        if d == self.day_filter:
            bg = CELL_PICK
        elif d == today:
            bg = CELL_TODAY

        cell = tk.Frame(self.mini_grid, bg=bg, cursor="hand2")
        cell.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)

        if d == self.day_filter:
            fg = "#ffffff"
        elif not in_month:
            fg = "#cbd5e1"
        elif d.weekday() == 6:
            fg = SUN_C
        elif d.weekday() == 5:
            fg = SAT_C
        else:
            fg = FG
        f = self.f["calb"] if (d == today or d == self.day_filter) else self.f["cal"]
        tk.Label(cell, text=str(d.day), font=f, bg=bg, fg=fg).pack()

        dots = tk.Frame(cell, bg=bg)
        dots.pack()
        order = [OVERDUE, TODAY_C, MINE_C, NOTICE_C, SCHOOL_C]
        shown = [x for x in order if x in colors][:3]
        if not shown:
            tk.Label(dots, text=" ", font=self.f["small"], bg=bg).pack()
        for col in shown:
            tk.Label(dots, text="●", font=self.f["small"], bg=bg,
                     fg=("#ffffff" if d == self.day_filter else col)).pack(side="left")

        def pick(_=None, day=d):
            self._pick_day(day)

        for w in (cell, dots) + tuple(cell.winfo_children()):
            try:
                w.bind("<Button-1>", pick)
            except Exception:
                pass

    def _shift_month(self, delta):
        m = self.cal_m + delta
        y = self.cal_y
        if m < 1:
            m, y = 12, y - 1
        elif m > 12:
            m, y = 1, y + 1
        self.cal_y, self.cal_m = y, m
        self.refresh()

    def _pick_day(self, day):
        self.day_filter = None if day == self.day_filter else day
        self.refresh()

    # ---- 큰 달력 ----
    def _open_calendar(self):
        try:
            from .calendar_view import CalendarWindow
            CalendarWindow(self.root)
        except Exception as e:
            self._gs_note = f"달력을 열지 못했습니다: {e}"
            self._paint_status()

    # ---- 원래 쪽지 열기 ----
    def _open_original(self, r: dict):
        src = (r.get("src_from") or r.get("source") or "brity")
        label = "GOE메신저" if src == "goe" else "브리티"
        self._gs_note = f"{label}에서 원래 쪽지를 찾는 중…"
        self._paint_status()

        def work():
            try:
                from . import reopen
                from .collector import BrityCollector
                # UI Automation 은 스레드마다 COM 초기화가 필요하다.
                # 빼먹으면 'CoInitialize가 호출되지 않았습니다' 로 실패한다 (실제 발생).
                with BrityCollector.init_thread():
                    ok, msg = reopen.open_original(
                        self.cfg, src, r.get("msg_id") or "",
                        subject=r.get("src_subject") or r.get("title") or "",
                        sender=r.get("src_sender") or "")
            except Exception as e:
                ok, msg = False, f"열지 못했습니다: {e}"
            self._gs_note = msg.split("\n")[0]
            try:
                self.root.after(0, self._paint_status)
                if not ok:
                    self.root.after(0, lambda: self._toast(msg))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _toast(self, msg: str):
        from tkinter import messagebox
        messagebox.showinfo(APP_NAME, msg)

    # ------------------------------------------------------------------
    def _run_now(self):
        self.run_btn.configure(state="disabled", text="정리 중…")

        def work():
            try:
                if getattr(sys, "frozen", False):
                    cmd = [sys.executable, "--force"]
                else:
                    cmd = [sys.executable,
                           str(Path(__file__).resolve().parents[1] / "run.py"), "--force"]
                subprocess.run(cmd, capture_output=True)
            except Exception:
                pass
            self.root.after(0, lambda: (
                self.run_btn.configure(state="normal", text="⟳  지금 쪽지 정리"),
                self.refresh()))

        threading.Thread(target=work, daemon=True).start()

    def run(self):
        self.root.mainloop()


def show():
    # 이미 떠 있으면 새로 띄우지 않는다 (로그온 자동 실행과 수동 실행이 겹칠 수 있다)
    if already_running():
        return
    Widget().run()
