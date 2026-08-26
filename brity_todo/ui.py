# -*- coding: utf-8 -*-
"""
교사 확인 UI (tkinter, 추가 설치 불필요).

흐름
  1) ask_start()    : "새 쪽지 N건. 정리해서 캘린더에 저장할까요?"  ← 첫 확인
  2) Progress       : 수집·추출 진행 상황
  3) review_tasks() : 추출 결과 검토 후 선택 저장          ← 최종 확인
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from datetime import datetime, date
from typing import List, Optional

BG = "#ffffff"
PAGE = "#eef1f6"         # 창 바탕 (옅은 회색)
HEAD = "#0f172a"         # 머리말 띠 (짙은 남색)
HEAD_SUB = "#94a3b8"
LINE = "#dde3ec"
FG = "#0f172a"
MUTED = "#64748b"
FAINT = "#94a3b8"
ACCENT = "#2563eb"
DANGER = "#b91c1c"
WARN_BG = "#fef3c7"


def _header(root, title: str, sub: str = ""):
    """패널과 같은 짙은 남색 머리말 띠."""
    f = _fonts()
    band = tk.Frame(root, bg=HEAD)
    band.pack(fill="x")
    tk.Label(band, text=title, font=f["title"], bg=HEAD, fg="#f8fafc")\
        .pack(anchor="w", padx=22, pady=(16, 0 if sub else 16))
    if sub:
        tk.Label(band, text=sub, font=f["small"], bg=HEAD, fg=HEAD_SUB)\
            .pack(anchor="w", padx=22, pady=(2, 14))
    return band


def _pill(parent, text: str, bg: str, fg: str = "white"):
    f = _fonts()
    return tk.Label(parent, text=text, font=f["small"], bg=bg, fg=fg,
                    padx=7, pady=1)


def _dpi_aware():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _center(win, w, h):
    """
    화면 중앙에 배치한다.

    주의: 화면 배율(DPI)이 100%가 아니면 요청한 크기보다 작게 잡혀
          하단 버튼이 잘린다. tk 의 scaling 값으로 보정하고,
          화면 높이를 넘지 않도록 제한한다.
    """
    win.update_idletasks()
    try:
        scale = float(win.tk.call("tk", "scaling")) / 1.3333
    except Exception:
        scale = 1.0
    scale = max(1.0, min(scale, 2.0))
    w = int(w * scale)
    h = int(h * scale)
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    h = min(h, sh - 80)
    w = min(w, sw - 40)
    win.minsize(min(520, w), min(420, h))
    win.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2 - 40)}")


def _fonts():
    return {
        "title": tkfont.Font(family="맑은 고딕", size=14, weight="bold"),
        "sub": tkfont.Font(family="맑은 고딕", size=10),
        "body": tkfont.Font(family="맑은 고딕", size=10),
        "small": tkfont.Font(family="맑은 고딕", size=9),
        "bold": tkfont.Font(family="맑은 고딕", size=10, weight="bold"),
    }


class ScrollFrame(ttk.Frame):
    """세로 스크롤 가능한 컨테이너."""

    def __init__(self, parent, height=300):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, height=height)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>",
                             lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))


# --------------------------------------------------------------------------
# 1) 시작 확인
# --------------------------------------------------------------------------
def ask_start(notes: List, window_from: Optional[datetime],
              days_gap: Optional[int] = None,
              stale_warning: Optional[str] = None) -> str:
    """
    반환: 'run' (정리하기) | 'later' (나중에) | 'preview' (미리보기만)
    """
    _dpi_aware()
    root = tk.Tk()
    root.title("BrityTodo — 쪽지 정리")
    root.configure(bg=PAGE)
    f = _fonts()
    result = {"v": "later"}

    today = datetime.now()
    since = window_from.strftime("%m월 %d일 %H:%M") if window_from else "최근"
    _header(root,
            f"{today.strftime('%m월 %d일')} 쪽지 정리",
            f"{since} 이후 도착한 쪽지 {len(notes)}건")

    if stale_warning:
        wf = tk.Frame(root, bg=WARN_BG)
        wf.pack(fill="x", padx=22, pady=(8, 0))
        tk.Label(wf, text=f"⚠ {stale_warning}", font=f["small"],
                 bg=WARN_BG, fg="#92400e", wraplength=560,
                 justify="left").pack(anchor="w", padx=10, pady=7)

    # 버튼과 안내문을 먼저 하단에 고정한다.
    # 목록을 먼저 채우면 창이 작을 때 버튼이 화면 밖으로 밀려 잘린다.
    foot = tk.Frame(root, bg=BG)
    foot.pack(side="bottom", fill="x")
    tk.Frame(foot, bg=LINE, height=1).pack(fill="x")
    btns = tk.Frame(foot, bg=BG)
    btns.pack(fill="x", padx=22, pady=(10, 16))
    _note = ("쪽지를 열어 본문을 읽으므로 메신저에서 '읽음'으로 표시됩니다. "
             "답장·삭제는 하지 않습니다.")
    tk.Label(foot, text=_note, font=f["small"], bg=BG, fg=FAINT,
             wraplength=560, justify="left").pack(anchor="w", padx=22,
                                                  pady=(0, 10))

    tk.Label(root, text="정리 대상", font=f["bold"], bg=PAGE, fg=MUTED)\
        .pack(anchor="w", padx=22, pady=(14, 6))

    sf = ScrollFrame(root, height=200)
    sf.pack(fill="both", expand=True, padx=16)

    if not notes:
        tk.Label(sf.inner, text="새로 도착한 쪽지가 없습니다.",
                 font=f["body"], bg=PAGE, fg=MUTED).pack(anchor="w", pady=12)
    for n in notes:
        card = tk.Frame(sf.inner, bg=BG, highlightbackground=LINE,
                        highlightthickness=1)
        card.pack(fill="x", pady=3, padx=6)
        stripe = tk.Frame(card, bg=ACCENT, width=4)
        stripe.pack(side="left", fill="y")
        left = tk.Frame(card, bg=BG)
        left.pack(side="left", fill="x", expand=True, padx=10, pady=7)
        tk.Label(left, text=n.preview[:58] + ("…" if len(n.preview) > 58 else ""),
                 font=f["body"], bg=BG, fg=FG, anchor="w", justify="left")\
            .pack(anchor="w")
        meta = f"{n.sender} · {n.date_text}" + ("  📎" if n.has_attach else "")
        tk.Label(left, text=meta, font=f["small"], bg=BG, fg=FAINT, anchor="w")\
            .pack(anchor="w")

    def choose(v):
        result["v"] = v
        root.destroy()

    tk.Button(btns, text="나중에", font=f["body"], width=10,
              command=lambda: choose("later")).pack(side="right", padx=(8, 0))
    run_btn = tk.Button(btns, text="정리해서 캘린더에 저장", font=f["bold"],
                        bg=ACCENT, fg="white", activebackground="#1e40af",
                        activeforeground="white", relief="flat", padx=16, pady=6,
                        command=lambda: choose("run"))
    run_btn.pack(side="right")
    tk.Button(btns, text="본문 열지 않고 목록만", font=f["small"],
              command=lambda: choose("preview")).pack(side="left")

    if not notes:
        run_btn.configure(state="disabled")

    _center(root, 620, 560)
    root.bind("<Escape>", lambda e: choose("later"))
    run_btn.focus_set()
    root.mainloop()
    return result["v"]


# --------------------------------------------------------------------------
# 2) 진행 표시
# --------------------------------------------------------------------------
class Progress:
    def __init__(self, total: int):
        _dpi_aware()
        self.root = tk.Tk()
        self.root.title("BrityTodo — 정리 중")
        self.root.configure(bg=BG)
        f = _fonts()
        tk.Label(self.root, text="쪽지를 읽고 있습니다", font=f["title"],
                 bg=BG, fg=FG).pack(anchor="w", padx=22, pady=(20, 4))
        self.msg = tk.Label(self.root, text="준비 중…", font=f["sub"],
                            bg=BG, fg=MUTED, anchor="w", wraplength=440, justify="left")
        self.msg.pack(anchor="w", padx=22)
        self.bar = ttk.Progressbar(self.root, mode="determinate",
                                   maximum=max(1, total), length=440)
        self.bar.pack(padx=22, pady=(14, 6))
        self.hint = tk.Label(self.root,
                             text="이 동안 다른 작업을 하셔도 됩니다. 창을 클릭하지 마세요.",
                             font=f["small"], bg=BG, fg=MUTED)
        self.hint.pack(anchor="w", padx=22, pady=(0, 18))
        _center(self.root, 500, 210)
        self.root.attributes("-topmost", True)
        self.root.update()

    def step(self, i: int, text: str):
        try:
            self.bar["value"] = i
            self.msg.configure(text=text)
            self.root.update()
        except Exception:
            pass

    def close(self):
        try:
            self.root.destroy()
        except Exception:
            pass


# --------------------------------------------------------------------------
# 3) 결과 검토
# --------------------------------------------------------------------------
def review_tasks(items: List[dict], auto_threshold: float = 0.85) -> Optional[List[dict]]:
    """
    items: [{title, due_at, due_kind, requester, category, confidence, warn,
             detail, msg_id, thread_key, _extracted}]
    반환: 승인된 항목 목록(due_at 이 사용자가 수정한 값으로 반영됨). 취소 시 None.
    """
    _dpi_aware()
    root = tk.Tk()
    root.title("BrityTodo — 저장할 일정 확인")
    root.configure(bg=PAGE)
    f = _fonts()
    out = {"v": None}
    today = date.today()

    _header(root, "저장할 일정을 확인해 주세요",
            f"할 일 {len(items)}건 · 체크된 것만 저장됩니다 · 제목과 마감일을 고칠 수 있습니다")

    # 저장 버튼도 하단에 먼저 고정한다 (창이 작아도 잘리지 않게)
    footwrap = tk.Frame(root, bg=BG)
    footwrap.pack(side="bottom", fill="x")
    tk.Frame(footwrap, bg=LINE, height=1).pack(fill="x")
    bar = tk.Frame(footwrap, bg=BG)
    bar.pack(fill="x", padx=22, pady=(10, 16))

    sf = ScrollFrame(root, height=340)
    sf.pack(fill="both", expand=True, padx=16, pady=(10, 0))

    rows = []
    if not items:
        tk.Label(sf.inner, text="추출된 할 일이 없습니다.",
                 font=f["body"], bg=PAGE, fg=MUTED).pack(anchor="w", pady=14)

    for it in items:
        conf = float(it.get("confidence") or 0)
        due = it.get("due_at") or ""
        due_disp = due.replace("T", " ")
        is_today = bool(due and due[:10] == today.isoformat())
        is_past = bool(due and due[:10] < today.isoformat())

        outer = tk.Frame(sf.inner, bg=BG, highlightbackground=LINE,
                         highlightthickness=1)
        outer.pack(fill="x", pady=4, padx=6)
        stripe_c = DANGER if (is_today or is_past) else (
            "#94a3b8" if conf < 0.6 else ACCENT)
        tk.Frame(outer, bg=stripe_c, width=4).pack(side="left", fill="y")
        card = tk.Frame(outer, bg=BG)
        card.pack(side="left", fill="x", expand=True)

        top = tk.Frame(card, bg=BG)
        top.pack(fill="x", padx=10, pady=(9, 2))

        var = tk.BooleanVar(value=bool(due) and conf >= 0.6)
        cb = tk.Checkbutton(top, variable=var, bg=BG, activebackground=BG)
        cb.pack(side="left")

        tl = tk.Frame(top, bg=BG)
        tl.pack(side="left", fill="x", expand=True)

        # 제목은 수정 가능하게 둔다.
        # 본문에서 뽑은 문장이 조각으로 잡히는 경우가 있어 손볼 수 있어야 한다.
        title_var = tk.StringVar(value=it["title"])
        te = tk.Entry(tl, textvariable=title_var, font=f["bold"], bg=BG, fg=FG,
                      relief="flat", highlightthickness=1,
                      highlightbackground="#e5e7eb", highlightcolor=ACCENT)
        te.pack(anchor="w", fill="x", expand=True, ipady=3)

        bl = tk.Frame(tl, bg=BG)
        bl.pack(anchor="w", pady=(3, 0))
        if is_today:
            _pill(bl, "오늘 마감", DANGER).pack(side="left", padx=(0, 4))
        elif is_past:
            _pill(bl, "기한 지남", DANGER).pack(side="left", padx=(0, 4))
        if it.get("_carried"):
            _pill(bl, "지난번 보류", "#e2e8f0", MUTED).pack(side="left", padx=(0, 4))
        if it.get("category"):
            _pill(bl, it["category"], "#e0e7ff", "#1e40af").pack(side="left",
                                                                 padx=(0, 4))
        if conf < 0.6:
            _pill(bl, "확인 필요", "#fef3c7", "#92400e").pack(side="left",
                                                              padx=(0, 4))
        elif conf >= auto_threshold:
            _pill(bl, "자동 등록 권장", "#dcfce7", "#166534").pack(side="left",
                                                                   padx=(0, 4))

        mid = tk.Frame(card, bg=BG)
        mid.pack(fill="x", padx=34, pady=(2, 4))
        tk.Label(mid, text="마감", font=f["small"], bg=BG, fg=MUTED).pack(side="left")
        ent = tk.Entry(mid, font=f["body"], width=20)
        ent.insert(0, due_disp)
        ent.pack(side="left", padx=(8, 10))
        req = it.get("requester") or ""
        tk.Label(mid, text=req, font=f["small"], bg=BG, fg=MUTED).pack(side="left")

        if it.get("detail"):
            tk.Label(card, text=it["detail"][:150], font=f["small"], bg=BG,
                     fg=MUTED, anchor="w", justify="left", wraplength=540)\
                .pack(anchor="w", padx=34, pady=(0, 4))

        if it.get("warn"):
            wf = tk.Frame(card, bg=WARN_BG)
            wf.pack(fill="x", padx=34, pady=(0, 8))
            tk.Label(wf, text=f"⚠ {it['warn']}", font=f["small"], bg=WARN_BG,
                     fg="#92400e", anchor="w", justify="left", wraplength=520)\
                .pack(anchor="w", padx=8, pady=5)
        else:
            tk.Frame(card, bg=BG, height=4).pack()

        rows.append((it, var, ent, title_var))

    def toggle_all(v):
        for _, var, _, _ in rows:
            var.set(v)

    tk.Button(bar, text="모두 선택", font=f["small"],
              command=lambda: toggle_all(True)).pack(side="left")
    tk.Button(bar, text="모두 해제", font=f["small"],
              command=lambda: toggle_all(False)).pack(side="left", padx=(6, 0))

    def cancel():
        out["v"] = None
        root.destroy()

    def save():
        approved = []
        for it, var, ent, title_var in rows:
            if not var.get():
                continue
            txt = ent.get().strip()
            if not txt:
                messagebox.showwarning("마감일 필요",
                                       f"'{it['title'][:30]}' 의 마감일을 입력하거나 체크를 해제하세요.")
                return
            norm = txt.replace(" ", "T") if " " in txt else txt
            try:
                datetime.fromisoformat(norm)
            except ValueError:
                messagebox.showwarning(
                    "날짜 형식 오류",
                    f"'{txt}' 를 해석할 수 없습니다.\nYYYY-MM-DD 또는 YYYY-MM-DD HH:MM 형식으로 입력해 주세요.")
                return
            new_title = title_var.get().strip()
            if not new_title:
                messagebox.showwarning("제목 필요",
                                       "제목이 비어 있습니다. 입력하거나 체크를 해제해 주세요.")
                return
            item = dict(it)
            item["due_at"] = norm
            item["title"] = new_title
            approved.append(item)
        out["v"] = approved
        root.destroy()

    tk.Button(bar, text="취소", font=f["body"], width=8, command=cancel)\
        .pack(side="right", padx=(8, 0))
    save_btn = tk.Button(bar, text="선택 항목 캘린더에 저장", font=f["bold"],
                         bg=ACCENT, fg="white", activebackground="#1e40af",
                         activeforeground="white", relief="flat", padx=16, pady=6,
                         command=save)
    save_btn.pack(side="right")
    if not items:
        save_btn.configure(state="disabled")

    _center(root, 640, 620)
    root.bind("<Escape>", lambda e: cancel())
    root.mainloop()
    return out["v"]


# --------------------------------------------------------------------------
# 결과 요약
# --------------------------------------------------------------------------
def show_summary(lines: List[str], title: str = "BrityTodo — 완료",
                 open_folder: Optional[str] = None) -> None:
    _dpi_aware()
    root = tk.Tk()
    root.title(title)
    root.configure(bg=PAGE)
    f = _fonts()
    _header(root, "정리를 마쳤습니다")
    card = tk.Frame(root, bg=BG, highlightbackground=LINE, highlightthickness=1)
    card.pack(fill="both", expand=True, padx=16, pady=(14, 0))
    body = tk.Frame(card, bg=BG)
    body.pack(fill="both", expand=True, padx=14, pady=10)
    for ln in lines:
        tk.Label(body, text=ln, font=f["body"], bg=BG, fg=FG,
                 anchor="w", justify="left", wraplength=500).pack(anchor="w", pady=2)
    btns = tk.Frame(root, bg=PAGE)
    btns.pack(pady=(14, 18))
    if open_folder:
        def _open():
            try:
                import os
                os.startfile(open_folder)
            except Exception:
                pass
        tk.Button(btns, text="파일 폴더 열기", font=f["body"],
                  command=_open).pack(side="left", padx=(0, 8))
    tk.Button(btns, text="닫기", font=f["body"], width=10,
              command=root.destroy).pack(side="left")
    _center(root, 560, 120 + 26 * max(1, len(lines)))
    root.mainloop()


def show_error(msg: str) -> None:
    _dpi_aware()
    r = tk.Tk()
    r.withdraw()
    messagebox.showerror("BrityTodo — 오류", msg)
    r.destroy()
