# -*- coding: utf-8 -*-
"""
자체 달력.

왜 자체로 만드는가
------------------
구글 캘린더는 각자 계정을 연결해야 하고(구글이 비밀번호 방식을 막았다),
윈도우 달력도 결국 Microsoft 계정 로그인을 요구한다.
여러 선생님께 나눠 드릴 물건에는 둘 다 걸림돌이다.

이 달력은 계정도 인터넷도 필요 없다. 프로그램만 있으면 바로 열린다.
쪽지에서 뽑은 할 일과 직접 넣은 학사일정을 한 판에 놓고 본다.

  · 쪽지에서 나온 할 일   — 마감 시각과 함께, 급한 것은 붉게
  · 학사일정             — 직접 추가하거나 .ics 파일로 가져오기
"""
from __future__ import annotations

import calendar as pycal
import re
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from tkinter import font as tkfont
from typing import Dict, List, Optional

from . import config
from .state import State

BG = "#ffffff"
HEAD_BG = "#1e293b"
HEAD_FG = "#f8fafc"
FG = "#111827"
MUTED = "#6b7280"
FAINT = "#9ca3af"
LINE = "#e5e7eb"
GRID = "#eef2f7"
TODAY_BG = "#eff6ff"
SAT = "#1d4ed8"
SUN = "#b91c1c"
OVERDUE = "#991b1b"
MINE = "#0f766e"        # 내 할 일
NOTICE = "#7c3aed"      # 알아둘 일
SCHOOL = "#b45309"      # 학사일정

WEEK_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _dpi():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _month_range(y: int, m: int):
    first = date(y, m, 1)
    last = date(y, m, pycal.monthrange(y, m)[1])
    # 달력 판은 월요일 시작
    start = first - timedelta(days=first.weekday())
    end = last + timedelta(days=(6 - last.weekday()))
    return first, last, start, end


class CalendarWindow:
    def __init__(self, master: Optional[tk.Misc] = None):
        _dpi()
        self.cfg = config.load()
        today = date.today()
        self.y, self.m = today.year, today.month
        self.selected: date = today

        self.root = tk.Toplevel(master) if master else tk.Tk()
        self.root.title("BrityTodo 달력")
        self.root.configure(bg=BG)
        self.f = {
            "title": tkfont.Font(family="맑은 고딕", size=13, weight="bold"),
            "wk": tkfont.Font(family="맑은 고딕", size=9, weight="bold"),
            "day": tkfont.Font(family="맑은 고딕", size=9, weight="bold"),
            "item": tkfont.Font(family="맑은 고딕", size=8),
            "btn": tkfont.Font(family="맑은 고딕", size=9),
            "side": tkfont.Font(family="맑은 고딕", size=9),
            "sidebold": tkfont.Font(family="맑은 고딕", size=10, weight="bold"),
        }
        self._build()
        self.refresh()
        self._center(1040, 720)

    def _center(self, w, h):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        h = min(h, sh - 80)
        self.root.geometry(f"{w}x{h}+{max(0,(sw-w)//2)}+{max(0,(sh-h)//2-30)}")

    # ------------------------------------------------------------------
    def _build(self):
        head = tk.Frame(self.root, bg=HEAD_BG, height=46)
        head.pack(fill="x")
        head.pack_propagate(False)

        tk.Label(head, text="◀", font=self.f["title"], bg=HEAD_BG, fg=HEAD_FG,
                 cursor="hand2").pack(side="left", padx=(14, 6))
        head.winfo_children()[-1].bind("<Button-1>", lambda e: self._move(-1))

        self.title_lbl = tk.Label(head, text="", font=self.f["title"],
                                  bg=HEAD_BG, fg=HEAD_FG, width=12)
        self.title_lbl.pack(side="left")

        nxt = tk.Label(head, text="▶", font=self.f["title"], bg=HEAD_BG,
                       fg=HEAD_FG, cursor="hand2")
        nxt.pack(side="left", padx=(6, 14))
        nxt.bind("<Button-1>", lambda e: self._move(1))

        tk.Button(head, text="오늘", font=self.f["btn"], relief="flat",
                  command=self._go_today).pack(side="left")

        tk.Button(head, text="닫기", font=self.f["btn"], relief="flat",
                  command=self.root.destroy).pack(side="right", padx=12)
        tk.Button(head, text="학사일정 가져오기(.ics)", font=self.f["btn"],
                  relief="flat", command=self._import_ics).pack(side="right", padx=6)
        tk.Button(head, text="+ 학사일정 추가", font=self.f["btn"], relief="flat",
                  command=self._add_event).pack(side="right", padx=6)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True)

        # 왼쪽: 달력 판
        self.grid_fr = tk.Frame(body, bg=BG)
        self.grid_fr.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        # 오른쪽: 고른 날 상세
        side = tk.Frame(body, bg=BG, width=290)
        side.pack(side="right", fill="y", padx=(0, 12), pady=10)
        side.pack_propagate(False)
        self.side_title = tk.Label(side, text="", font=self.f["sidebold"],
                                   bg=BG, fg=FG, anchor="w")
        self.side_title.pack(fill="x", pady=(0, 6))
        tk.Frame(side, bg=LINE, height=1).pack(fill="x")
        self.side_body = tk.Frame(side, bg=BG)
        self.side_body.pack(fill="both", expand=True, pady=6)

        legend = tk.Frame(self.root, bg=BG)
        legend.pack(fill="x", padx=14, pady=(0, 10))
        for color, label in ((MINE, "내 할 일"), (NOTICE, "알아둘 일"),
                             (SCHOOL, "학사일정"), (OVERDUE, "기한 지남")):
            box = tk.Frame(legend, bg=BG)
            box.pack(side="left", padx=(0, 14))
            tk.Label(box, text="■", font=self.f["item"], bg=BG, fg=color).pack(side="left")
            tk.Label(box, text=label, font=self.f["item"], bg=BG, fg=MUTED).pack(side="left")

    # ------------------------------------------------------------------
    def _move(self, delta: int):
        m = self.m + delta
        y = self.y
        if m < 1:
            m, y = 12, y - 1
        elif m > 12:
            m, y = 1, y + 1
        self.y, self.m = y, m
        self.refresh()

    def _go_today(self):
        t = date.today()
        self.y, self.m, self.selected = t.year, t.month, t
        self.refresh()

    # ------------------------------------------------------------------
    def _load(self, start: date, end: date):
        st = State()
        try:
            tasks = [dict(r) for r in st.tasks_between(start.isoformat(),
                                                       end.isoformat())]
            events = [dict(r) for r in st.school_events_between(start.isoformat(),
                                                                end.isoformat())]
        finally:
            st.close()

        by_day: Dict[date, List[dict]] = {}
        for t in tasks:
            d = date.fromisoformat(t["due_at"][:10])
            kind = (t.get("kind") or "mine")
            by_day.setdefault(d, []).append({
                "kind": kind,
                "color": OVERDUE if d < date.today() else (
                    MINE if kind == "mine" else NOTICE),
                "time": t["due_at"][11:16] if "T" in (t["due_at"] or "") else "",
                "title": t.get("short_title") or t["title"],
                "raw": t,
                "type": "task",
            })
        for e in events:
            s = date.fromisoformat(e["start_date"])
            fin = date.fromisoformat(e["end_date"] or e["start_date"])
            d = s
            while d <= fin:
                if start <= d <= end:
                    by_day.setdefault(d, []).append({
                        "kind": "school",
                        "color": SCHOOL,
                        "time": e["start_time"] or "",
                        "title": e["title"],
                        "raw": e,
                        "type": "school",
                    })
                d += timedelta(days=1)

        for v in by_day.values():
            v.sort(key=lambda x: (x["time"] == "", x["time"]))
        return by_day

    # ------------------------------------------------------------------
    def refresh(self):
        for w in self.grid_fr.winfo_children():
            w.destroy()
        first, last, start, end = _month_range(self.y, self.m)
        self.title_lbl.configure(text=f"{self.y}년 {self.m}월")
        data = self._load(start, end)

        for i, wk in enumerate(WEEK_KO):
            fg = SUN if i == 6 else (SAT if i == 5 else MUTED)
            tk.Label(self.grid_fr, text=wk, font=self.f["wk"], bg=BG, fg=fg)\
                .grid(row=0, column=i, sticky="nsew", pady=(0, 4))

        rows = (end - start).days // 7 + 1
        for i in range(7):
            self.grid_fr.grid_columnconfigure(i, weight=1, uniform="d")
        for r in range(1, rows + 1):
            self.grid_fr.grid_rowconfigure(r, weight=1, uniform="r")

        today = date.today()
        d = start
        for r in range(1, rows + 1):
            for c in range(7):
                self._cell(r, c, d, first, last, today, data.get(d, []))
                d += timedelta(days=1)

        self._paint_side()

    def _cell(self, r, c, d: date, first: date, last: date,
              today: date, items: List[dict]):
        in_month = first <= d <= last
        bg = TODAY_BG if d == today else BG
        cell = tk.Frame(self.grid_fr, bg=bg, highlightbackground=GRID,
                        highlightthickness=1, cursor="hand2")
        cell.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)

        fg = FAINT
        if in_month:
            fg = SUN if d.weekday() == 6 else (SAT if d.weekday() == 5 else FG)
        top = tk.Frame(cell, bg=bg)
        top.pack(fill="x", padx=5, pady=(3, 0))
        tk.Label(top, text=str(d.day), font=self.f["day"], bg=bg, fg=fg).pack(side="left")
        if d == self.selected:
            tk.Label(top, text="●", font=self.f["item"], bg=bg, fg="#2563eb").pack(side="right")

        shown = items[:3]
        for it in shown:
            txt = (it["time"] + " " if it["time"] else "") + it["title"]
            tk.Label(cell, text=txt[:16], font=self.f["item"], bg=bg,
                     fg=it["color"] if in_month else FAINT,
                     anchor="w").pack(fill="x", padx=5)
        if len(items) > 3:
            tk.Label(cell, text=f"+{len(items)-3}", font=self.f["item"],
                     bg=bg, fg=MUTED, anchor="w").pack(fill="x", padx=5)

        def pick(_=None, day=d):
            self.selected = day
            self.refresh()

        for w in [cell, top] + list(cell.winfo_children()):
            try:
                w.bind("<Button-1>", pick)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _paint_side(self):
        for w in self.side_body.winfo_children():
            w.destroy()
        d = self.selected
        self.side_title.configure(
            text=f"{d.month}월 {d.day}일 ({WEEK_KO[d.weekday()]})")
        items = self._load(d, d).get(d, [])
        if not items:
            tk.Label(self.side_body, text="이 날은 비어 있습니다.", font=self.f["side"],
                     bg=BG, fg=MUTED).pack(anchor="w", pady=8)
            return
        for it in items:
            card = tk.Frame(self.side_body, bg=BG)
            card.pack(fill="x", pady=5)
            line = tk.Frame(card, bg=BG)
            line.pack(fill="x")
            tk.Label(line, text="■", font=self.f["item"], bg=BG,
                     fg=it["color"]).pack(side="left", padx=(0, 5))
            if it["time"]:
                tk.Label(line, text=it["time"], font=self.f["sidebold"], bg=BG,
                         fg=it["color"]).pack(side="left", padx=(0, 6))
            tk.Label(line, text=it["title"][:40], font=self.f["side"], bg=BG,
                     fg=FG, anchor="w", justify="left", wraplength=200)\
                .pack(side="left", fill="x", expand=True)

            raw = it["raw"]
            if it["type"] == "school":
                sub = f"학사일정 · {raw.get('category') or ''}"
                rm = tk.Label(card, text="삭제", font=self.f["item"], bg=BG,
                              fg="#b91c1c", cursor="hand2")
                rm.pack(anchor="e")
                rm.bind("<Button-1>",
                        lambda e, i=raw["event_id"]: self._del_event(i))
            else:
                who = raw.get("src_sender") or (raw.get("requester") or "")
                origin = "GOE" if (raw.get("src_from") == "goe") else "브리티"
                sub = f"{origin} · {who}".strip(" ·")
            tk.Label(card, text=sub, font=self.f["item"], bg=BG, fg=FAINT,
                     anchor="w").pack(fill="x", padx=(18, 0))

    # ------------------------------------------------------------------
    def _add_event(self):
        title = simpledialog.askstring("학사일정 추가", "일정 이름", parent=self.root)
        if not title:
            return
        ds = simpledialog.askstring(
            "학사일정 추가",
            f"날짜 (YYYY-MM-DD)\n여러 날이면 'YYYY-MM-DD ~ YYYY-MM-DD'",
            initialvalue=self.selected.isoformat(), parent=self.root)
        if not ds:
            return
        parts = [p.strip() for p in re.split(r"~|-{2,}", ds) if p.strip()]
        try:
            s = date.fromisoformat(parts[0])
            e = date.fromisoformat(parts[1]) if len(parts) > 1 else s
        except ValueError:
            messagebox.showwarning("BrityTodo", "날짜를 YYYY-MM-DD 형식으로 넣어 주세요.",
                                   parent=self.root)
            return
        st = State()
        st.add_school_event(title, s.isoformat(), e.isoformat(), category="학사")
        st.close()
        self.selected = s
        self.y, self.m = s.year, s.month
        self.refresh()

    def _del_event(self, event_id: int):
        if not messagebox.askyesno("BrityTodo", "이 학사일정을 지울까요?",
                                   parent=self.root):
            return
        st = State()
        st.delete_school_event(event_id)
        st.close()
        self.refresh()

    def _import_ics(self):
        path = filedialog.askopenfilename(
            title="학사일정 파일(.ics) 선택",
            filetypes=[("캘린더 파일", "*.ics"), ("모든 파일", "*.*")],
            parent=self.root)
        if not path:
            return
        try:
            n, dup = import_ics(Path(path))
        except Exception as e:
            messagebox.showerror("BrityTodo", f"가져오지 못했습니다.\n\n{e}",
                                 parent=self.root)
            return
        messagebox.showinfo(
            "BrityTodo",
            f"학사일정 {n}건을 가져왔습니다." +
            (f"\n(이미 있던 {dup}건은 건너뛰었습니다)" if dup else ""),
            parent=self.root)
        self.refresh()

    def run(self):
        self.root.mainloop()


# --------------------------------------------------------------------------
_DT = re.compile(r"^(DTSTART|DTEND)[^:]*:(\d{8})(?:T(\d{2})(\d{2}))?")
_SUM = re.compile(r"^SUMMARY:(.*)$")


def import_ics(path: Path):
    """
    .ics 파일에서 일정을 읽어 학사일정으로 넣는다.
    학교에서 내려받은 학사일정 파일이나, 다른 캘린더에서 내보낸 파일을 쓸 수 있다.
    """
    text = path.read_text(encoding="utf-8", errors="ignore")
    # 접힌 줄(다음 줄이 공백으로 시작) 펴기
    text = re.sub(r"\r?\n[ \t]", "", text)

    added = dup = 0
    st = State()
    try:
        for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
            title = ""
            start = end = None
            stime = None
            for line in block.splitlines():
                line = line.strip()
                ms = _SUM.match(line)
                if ms:
                    title = (ms.group(1).replace("\\,", ",")
                             .replace("\\;", ";").replace("\\n", " ").strip())
                    continue
                md = _DT.match(line)
                if md:
                    kind, ymd, hh, mm = md.groups()
                    try:
                        d = datetime.strptime(ymd, "%Y%m%d").date()
                    except ValueError:
                        continue
                    if kind == "DTSTART":
                        start = d
                        if hh:
                            stime = f"{hh}:{mm}"
                    else:
                        end = d
            if not title or not start:
                continue
            # 종일 일정의 DTEND 는 다음 날을 가리킨다
            if end and end > start and stime is None:
                end = end - timedelta(days=1)
            end = end or start
            if st.school_event_exists(title, start.isoformat()):
                dup += 1
                continue
            st.add_school_event(title, start.isoformat(), end.isoformat(),
                                stime, "학사", "", "ics")
            added += 1
    finally:
        st.close()
    return added, dup


def show(master=None):
    CalendarWindow(master).run()
