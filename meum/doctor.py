# -*- coding: utf-8 -*-
"""
진단 보고서.

'브리티를 켜 뒀는데 연결이 안 된다' 같은 문제는 그 컴퓨터에서만 나타난다.
원격으로 들여다볼 수 없으니, 프로그램이 무엇을 보고 그렇게 판단했는지를
그대로 적어 파일 하나로 남긴다. 선생님은 그 파일만 보내 주시면 된다.

개인정보는 담지 않는다 — 쪽지 본문·제목·발신자를 적지 않고,
'몇 건을 읽었다'는 숫자와 창·프로세스 정보만 적는다.
"""
from __future__ import annotations

import os
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path

import tkinter as tk

from . import APP_NAME, __version__, config
from .ui import BG, FG, MUTED, ACCENT, _fonts


def _line(t=""):
    return t + "\n"


def _section(title):
    return "\n" + "─" * 62 + "\n" + f" {title}\n" + "─" * 62 + "\n"


def _safe(fn, default="(확인 실패)"):
    try:
        return fn()
    except Exception as e:
        return f"{default} — {type(e).__name__}: {e}"


def _dpi_info() -> str:
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)   # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        w = ctypes.windll.user32.GetSystemMetrics(0)
        h = ctypes.windll.user32.GetSystemMetrics(1)
        return f"{w}x{h} · {dpi}dpi ({round(dpi / 96 * 100)}%)"
    except Exception as e:
        return f"(확인 실패: {e})"


def _safe_name(nm: str) -> str:
    """
    화면에 적힌 글자를 보고서에 담되, 쪽지 내용은 담지 않는다.

    단추·탭 이름은 짧다. 쪽지 제목이나 미리보기는 길다.
    그래서 긴 것은 글자 수만 적는다.
    """
    nm = (nm or "").strip()
    if not nm:
        return ""
    if len(nm) > 20:
        return f"(내용 생략 {len(nm)}자)"
    return nm


def _tree_dump(hwnd, maxdepth=14, limit=90) -> str:
    """창 안의 구조를 그대로 옮긴다. 어떤 창인지 판단하는 근거가 된다."""
    import uiautomation as auto
    from . import collector as C

    out = ""
    try:
        C.wake_accessibility(hwnd)
        root = auto.ControlFromHandle(hwnd)
        if root is None:
            return _line("   (트리를 열 수 없습니다)")
        n = 0
        for x, d in C._walk(root, maxdepth=maxdepth):
            n += 1
            if n > limit:
                out += _line(f"      … 이하 생략")
                break
            try:
                ct = x.ControlTypeName
                nm = _safe_name(x.Name)
            except Exception:
                continue
            out += _line(f"      {'  ' * min(d, 8)}{ct}{(' · ' + nm) if nm else ''}")
        if n == 0:
            out += _line("      (비어 있음 — 접근성 트리가 아직 열리지 않았습니다)")
    except Exception as e:
        out += _line(f"      (읽기 실패: {e})")
    return out


def _brity_section() -> str:
    out = _section("브리티 메신저")
    try:
        from . import collector as C
    except Exception as e:
        return out + _line(f"수집기를 불러오지 못했습니다: {e}")

    pids = _safe(lambda: sorted(C.brity_pids()), [])
    out += _line(f"실행 중인 프로세스 : {pids if pids else '없음'}")
    out += _line(f"실행 파일 경로     : {_safe(C.find_brity_exe)}")

    try:
        cands = C.brity_windows()
    except Exception as e:
        return out + _line(f"창 목록을 읽지 못했습니다: {e}")

    out += _line(f"창 후보 {len(cands)}개")
    try:
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread():
            for h, title, vis, area in cands:
                is_app = _safe(lambda h=h: "예" if C.window_is_app(h) else "아니오")
                out += _line(f"   hwnd={h:<10} 보임={'예' if vis else '아니오(트레이)':<14} "
                             f"본창={is_app:<7} 넓이={area:<10} 제목={title!r}")
    except Exception:
        for h, title, vis, area in cands:
            out += _line(f"   hwnd={h:<10} 보임={'예' if vis else '아니오(트레이)':<14} "
                         f"넓이={area:<10} 제목={title!r}")

    main = _safe(lambda: C.find_app_window(), None)
    out += _line(f"고른 본창          : {main}")

    # 창마다 안이 어떻게 생겼는지 그대로 적는다.
    # '목록 0개' 라는 결과만으로는 그 창이 무엇이었는지 알 수 없어,
    # 한 번의 보고서로 원인을 가릴 수 없었다(실제로 겪음).
    try:
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread():
            for h, title, vis, area in cands:
                out += _line()
                out += _line(f"   [창 {h} · {title!r} · "
                             f"{'보임' if vis else '숨김'}] 안의 구조")
                out += _tree_dump(h)

            # 접근성 트리가 늦게 열리는 경우가 있어 여러 번 세어 본다
            if main:
                out += _line()
                out += _line("   [본창 접근성 트리 — 시간을 두고 3번 확인]")
                import time as _t
                for i in range(3):
                    C.wake_accessibility(main)
                    _t.sleep(1.0 if i else 0.0)
                    root = auto.ControlFromHandle(main)
                    total = lists = 0
                    for x, _d in C._walk(root, maxdepth=25):
                        total += 1
                        try:
                            if x.ControlTypeName == "ListControl":
                                lists += 1
                        except Exception:
                            continue
                    out += _line(f"      {i + 1}회차: 노드 {total}개 · 목록 {lists}개")
    except Exception:
        out += _line("접근성 트리 확인 중 오류:\n" + traceback.format_exc())

    if not main:
        out += _line()
        out += _line("→ 쪽지 목록이 들어 있는 창이 없습니다. 브리티 창을 닫아 트레이에만"
                     " 두신 상태일 수 있습니다.")
        out += _line("   (이 경우 메움이 브리티에게 창을 열어 달라고 요청합니다)")
        return out

    # 실제 연결 절차를 그대로 밟아 본다
    out += _line()
    out += _line("[실제 연결 시도]")
    try:
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread():
            col = C.BrityCollector(config.load(), log=lambda s: None)
            col.attach()
            try:
                who = _safe(col.detect_my_name, "(못 읽음)")
                notes = col.list_notes(scroll_rounds=1)
                out += _line(f"   결과           : 성공")
                out += _line(f"   로그인 사용자  : {'확인됨' if who else '못 읽음'}")
                out += _line(f"   쪽지함 읽은 건수: {len(notes)}건")
            finally:
                col.restore()
    except Exception as e:
        out += _line(f"   결과           : 실패 — {type(e).__name__}")
        out += _line(f"   메시지         : {e}")
        out += _line("   자세히:")
        out += "".join("     " + l for l in traceback.format_exc().splitlines(True))
    return out


def _goe_section() -> str:
    out = _section("GOE메신저")
    try:
        from . import goe_collector as G
    except Exception as e:
        return out + _line(f"수집기를 불러오지 못했습니다: {e}")
    running = _safe(G.is_running, False)
    out += _line(f"실행 여부          : {running}")
    if not running:
        out += _line("→ GOE메신저가 없으면 조용히 건너뜁니다(정상).")
        return out
    try:
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread():
            col = G.GoeCollector(config.load(), log=lambda s: None)
            col.attach()
            out += _line(f"본창 hwnd          : {col.hwnd}")
            out += _line(f"쪽지 목록 hwnd     : {col.list_hwnd}")
            out += _line(f"열려 있는 쪽지 창  : {len(G._visible_notes())}개")
            col.restore()
    except Exception as e:
        out += _line(f"연결 실패 — {type(e).__name__}: {e}")
    return out


def _state_section() -> str:
    out = _section("프로그램 상태")
    cfg = _safe(config.load, {})
    if isinstance(cfg, dict):
        keys = ("run_time", "run_time_lunch", "times_confirmed", "auto_mode",
                "watch_enabled", "watch_idle_sec", "watch_idle_gap_min",
                "sources", "collect_mode", "launch_brity_if_closed")
        for k in keys:
            out += _line(f"   {k:<22} {cfg.get(k)}")
    out += _line(f"   데이터 폴더            {config.APP_DIR}")
    try:
        from .state import State
        st = State()
        try:
            n_msg = st.con.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"]
            n_task = st.con.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
            out += _line(f"   보관 쪽지 / 할 일      {n_msg}건 / {n_task}건")
            out += _line(f"   마지막 성공 실행       {st.last_run_at}")
            out += _line("   최근 실행 이력")
            rows = st.con.execute(
                "SELECT * FROM runs ORDER BY run_id DESC LIMIT 8").fetchall()
            for r in rows:
                out += _line(f"      {r['started_at']}  {r['trigger']:<8}"
                             f"{r['status']:<9} 수집 {r['collected']:<3} "
                             f"추출 {r['extracted']:<3} 저장 {r['synced']:<3}"
                             + (f"  · {(r['error'] or '')[:40]}" if r["error"] else ""))
        finally:
            st.close()
    except Exception as e:
        out += _line(f"   기록을 읽지 못했습니다: {e}")
    return out


def build_report() -> str:
    r = _line("=" * 62)
    r += _line(f" {APP_NAME} 진단 보고서")
    r += _line("=" * 62)
    r += _line(f"만든 시각   : {datetime.now():%Y-%m-%d %H:%M:%S}")
    r += _line(f"프로그램    : {APP_NAME} {__version__}")
    r += _line(f"실행 형태   : {'설치본(exe)' if getattr(sys, 'frozen', False) else '소스'}")
    r += _line(f"실행 경로   : {sys.executable}")
    r += _line(f"윈도우      : {platform.platform()}")
    r += _line(f"파이썬      : {platform.python_version()} "
               f"({'64' if sys.maxsize > 2**32 else '32'}비트)")
    r += _line(f"화면        : {_dpi_info()}")
    r += _brity_section()
    r += _goe_section()
    r += _state_section()
    r += _line()
    r += _line("이 파일에는 쪽지 내용·제목·발신자가 들어 있지 않습니다.")
    return r


def _desktop_dir() -> Path:
    """
    바탕화면 위치. OneDrive 로 옮겨 놓은 컴퓨터가 많아 레지스트리에서 먼저 읽는다.
    (Path.home()/'Desktop' 이 없는 컴퓨터가 실제로 있다)
    """
    try:
        import winreg
        k = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
        try:
            val, _ = winreg.QueryValueEx(k, "Desktop")
        finally:
            winreg.CloseKey(k)
        p = Path(os.path.expandvars(val))
        if p.exists():
            return p
    except Exception:
        pass
    for p in (Path.home() / "Desktop", Path.home() / "바탕 화면"):
        if p.exists():
            return p
    return config.APP_DIR


def save_report_text(text: str) -> Path:
    """이미 만든 보고서를 바탕화면에 저장하고 경로를 돌려준다."""
    path = _desktop_dir() / f"메움_진단_{datetime.now():%y%m%d_%H%M}.txt"
    path.write_text(text, encoding="utf-8", newline="\r\n")
    return path


def save_report() -> Path:
    """보고서를 새로 만들어 저장한다."""
    return save_report_text(build_report())


def send_report(text: str, endpoint: str = "") -> tuple:
    """
    보고서를 만든 사람에게 곧바로 보낸다 (설정에 주소가 있을 때만).

    학교 컴퓨터에는 서버도 없고, 남의 계정 정보를 프로그램에 넣어 둘 수도
    없다. 그래서 기본값은 '보내지 않음'이고, 선생님이 직접 만드신
    구글 폼 주소를 config 의 report_endpoint 에 넣어 두었을 때만 보낸다.

    반환: (보냈는가, 안내 문구)
    """
    endpoint = (endpoint or "").strip()
    if not endpoint:
        return False, ""
    try:
        import urllib.parse
        import urllib.request
        field = config.load().get("report_field", "entry.1000001")
        data = urllib.parse.urlencode({field: text[:60000]}).encode("utf-8")
        req = urllib.request.Request(
            endpoint, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = 200 <= r.status < 400
        return ok, ("보고서를 보냈습니다." if ok else "보내지 못했습니다.")
    except Exception as e:
        return False, f"보내지 못했습니다({type(e).__name__}). 파일로 전달해 주세요."


_ENTRY_RE = None


def configure_endpoint(form_url: str, save: bool = True) -> tuple:
    """
    구글 폼 주소 하나만 주면 보낼 준비를 끝낸다.

    폼에 글을 넣으려면 '어느 칸에 넣을지'를 가리키는 entry 번호가 필요한데,
    그걸 찾으라고 하면 페이지 소스를 열어 눈으로 뒤져야 한다. 그 대신
    폼 페이지를 한 번 읽어 번호를 직접 찾아낸다.

    반환: (성공, 안내 문구, {"report_endpoint": ..., "report_field": ...})
    """
    import re
    import urllib.request

    url = (form_url or "").strip()
    if not url:
        return False, "폼 주소가 비어 있습니다.", {}
    if "docs.google.com/forms" not in url:
        return False, "구글 폼 주소가 아닙니다.", {}

    view = re.sub(r"/(formResponse|viewform).*$", "/viewform", url)
    post = re.sub(r"/(formResponse|viewform).*$", "/formResponse", url)
    try:
        req = urllib.request.Request(
            view, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception as e:
        return False, f"폼 페이지를 열지 못했습니다: {e}", {}

    field = _find_entry_id(html)
    if not field:
        return False, ("폼에서 입력 칸을 찾지 못했습니다.\n"
                       "'장문형' 질문이 하나 있는 폼인지 확인해 주세요."), {}

    cfg = {"report_endpoint": post, "report_field": field}
    if save:
        config.update(**cfg)
    return True, f"보낼 준비가 되었습니다. (칸: {field})", cfg


def _find_entry_id(html: str):
    """폼 페이지에서 답을 넣을 칸의 entry 번호를 찾는다."""
    import re

    # 1) 가장 흔한 형태 — name="entry.123456789"
    m = re.search(r'name="(entry\.\d+)"', html)
    if m:
        return m.group(1)
    m = re.search(r'"(entry\.\d+)"', html)
    if m:
        return m.group(1)

    # 2) 요즘 폼은 FB_PUBLIC_LOAD_DATA_ 안에 번호만 들어 있다.
    #    질문 묶음이 [번호, "질문", ...] 꼴이라 첫 번째 큰 번호를 쓴다.
    m = re.search(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(.+?);\s*</script>", html, re.S)
    if m:
        nums = re.findall(r"\[(\d{6,}),", m.group(1))
        if nums:
            return f"entry.{nums[0]}"
    return None


def copy_to_clipboard(text: str) -> bool:
    """보고서를 클립보드에 담는다 — 카카오톡·메일에 바로 붙여넣도록."""
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()          # 이게 있어야 창을 닫아도 클립보드에 남는다
        r.destroy()
        return True
    except Exception:
        return False


def show_report_window(text, path, copied=False, sent=False,
                       sent_msg='', parent=None, endpoint=""):
    """
    진단 보고서를 보여 주고, **한 번 눌러 보내게** 한다.

    보내는 분은 컴퓨터가 어려우실 수 있다. 그래서 화면에 할 일을 하나만
    남긴다 — 큰 단추 하나. 긴 보고서 내용은 접어 두고, 원하실 때만 편다.

    받을 주소(report_endpoint)가 설정돼 있으면 그 단추가 '보내기'가 되고,
    없으면 '복사하기'가 된다. 복사한 뒤 카카오톡에 붙여넣으면 된다.
    """
    win = tk.Toplevel(parent) if parent else tk.Tk()
    win.title(f"{APP_NAME} 진단 보고서")
    win.configure(bg=BG)
    F = _fonts()          # 글꼴은 창이 생긴 뒤에야 만들 수 있다
    to_name = config.load().get("report_to", "만든 사람")

    head = tk.Frame(win, bg=BG)
    head.pack(fill="x", padx=22, pady=(20, 4))
    title_lbl = tk.Label(head, text="진단 결과가 준비되었습니다", font=F["title"],
                         bg=BG, fg=FG)
    title_lbl.pack(anchor="w")
    guide = tk.Label(head, text="", font=F["body"], bg=BG, fg=MUTED,
                     justify="left", wraplength=560)
    guide.pack(anchor="w", pady=(8, 0))

    # 큰 단추 하나
    act = tk.Frame(win, bg=BG)
    act.pack(fill="x", padx=22, pady=(16, 4))
    big = tk.Button(act, font=F["bold"], relief="flat", bg=ACCENT, fg="white",
                    activebackground="#1e40af", activeforeground="white",
                    cursor="hand2", padx=26, pady=12)
    big.pack(anchor="w")

    note = tk.Label(win, text="쪽지 내용·제목·발신자는 들어 있지 않습니다.",
                    font=F["small"], bg=BG, fg=MUTED)
    note.pack(anchor="w", padx=22, pady=(10, 0))

    # 접어 둔 본문
    body = tk.Frame(win, bg=BG)
    shown = {"open": False}

    def toggle():
        if shown["open"]:
            body.pack_forget()
            more.configure(text="▸ 보고서 내용 보기")
            win.geometry("620x330")
        else:
            body.pack(fill="both", expand=True, padx=22, pady=(8, 0))
            more.configure(text="▾ 내용 접기")
            win.geometry("720x620")
        shown["open"] = not shown["open"]

    more = tk.Label(win, text="▸ 보고서 내용 보기", font=F["small"], bg=BG,
                    fg=ACCENT, cursor="hand2")
    more.pack(anchor="w", padx=22, pady=(12, 0))
    more.bind("<Button-1>", lambda e: toggle())

    sb = tk.Scrollbar(body)
    sb.pack(side="right", fill="y")
    txt = tk.Text(body, font=("맑은 고딕", 9), wrap="none", bg="#ffffff",
                  fg=FG, yscrollcommand=sb.set, relief="solid", bd=1, height=12)
    txt.pack(fill="both", expand=True)
    sb.configure(command=txt.yview)
    txt.insert("1.0", text)
    txt.configure(state="disabled")

    foot = tk.Frame(win, bg=BG)
    foot.pack(side="bottom", fill="x", padx=22, pady=(10, 16))
    tk.Label(foot, text=f"저장 위치: {path.name}", font=F["small"],
             bg=BG, fg=MUTED).pack(side="left")

    def open_folder():
        import subprocess
        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
        except Exception:
            pass

    tk.Label(foot, text="파일 위치 열기", font=F["small"], bg=BG, fg=ACCENT,
             cursor="hand2").pack(side="left", padx=(12, 0))
    foot.winfo_children()[-1].bind("<Button-1>", lambda e: open_folder())
    tk.Button(foot, text="닫기", font=F["bold"], relief="flat",
              bg="#e2e8f0", fg=FG, cursor="hand2", padx=16, pady=6,
              command=win.destroy).pack(side="right")

    # ---- 상태에 따라 큰 단추의 역할이 바뀐다 ----
    def as_done():
        title_lbl.configure(text="보냈습니다")
        guide.configure(text=f"{to_name}께 진단 결과가 전달되었습니다.\n"
                             "이 창은 닫으셔도 됩니다.", fg="#166534")
        big.configure(text="닫기", bg="#166534", activebackground="#14532d",
                      command=win.destroy)

    def do_send():
        big.configure(state="disabled", text="보내는 중…")
        win.update()
        ok, msg = send_report(text, endpoint)
        if ok:
            as_done()
        else:
            copy_to_clipboard(text)
            title_lbl.configure(text="보내지 못했습니다")
            guide.configure(
                text=(msg or "보내지 못했습니다.") +
                     "\n내용을 복사해 두었습니다. 카카오톡 창에서 "
                     "붙여넣기(Ctrl+V) 해 주세요.", fg=DANGER)
            big.configure(state="normal", text="다시 복사하기", bg=ACCENT,
                          command=do_copy)

    def do_copy():
        copy_to_clipboard(text)
        title_lbl.configure(text="복사했습니다")
        guide.configure(text=f"카카오톡에서 {to_name}께 붙여넣기(Ctrl+V) 해 주세요.",
                        fg="#166534")
        big.configure(text="다시 복사하기")

    if sent:
        as_done()
    elif endpoint:
        guide.configure(text=f"{to_name}께 보내면 원인을 찾아 고쳐 드릴 수 있습니다.")
        big.configure(text=f"{to_name}께 보내기", command=do_send)
    else:
        if copied:
            guide.configure(text="내용을 복사해 두었습니다.\n"
                                 f"카카오톡에서 {to_name}께 "
                                 "붙여넣기(Ctrl+V) 만 하시면 됩니다.")
            big.configure(text="다시 복사하기", command=do_copy)
        else:
            guide.configure(text=f"복사한 뒤 카카오톡에서 {to_name}께 "
                                 "붙여넣어 주세요.")
            big.configure(text="내용 복사하기", command=do_copy)
        if sent_msg:
            guide.configure(text=guide.cget("text") + "\n" + sent_msg)

    win.geometry("620x330")
    try:
        win.update_idletasks()
        if parent is not None:
            x = parent.winfo_rootx() + 40
            y = parent.winfo_rooty() + 60
            win.geometry(f"+{x}+{y}")
    except Exception:
        pass

    if parent is None:
        # 혼자 띄웠을 때는 창이 닫힐 때까지 기다린다
        # (없으면 만들자마자 프로그램이 끝나 창이 사라진다)
        win.mainloop()
    return win


def run_doctor(show: bool = True) -> int:
    """
    진단 보고서를 만들어 저장하고, 곧바로 보낼 수 있는 창을 띄운다.

    파일을 찾아 첨부해 보내는 일까지 부탁드리면 거기서 끊긴다.
    그래서 만들자마자 클립보드에 담고, 창에서 바로 붙여넣을 수 있게 한다.
    """
    text = build_report()
    path = save_report_text(text)
    copied = copy_to_clipboard(text)
    sent, sent_msg = send_report(text, config.load().get("report_endpoint", ""))

    if sys.stdout is not None:
        try:
            print(f"진단 보고서를 저장했습니다:\n  {path}")
        except Exception:
            pass

    if show:
        try:
            show_report_window(text, path, copied, sent, sent_msg,
                               endpoint=config.load().get('report_endpoint', ''))
        except Exception:
            try:
                os.startfile(str(path))      # 창을 못 띄우면 메모장으로라도
            except Exception:
                pass
    return 0
