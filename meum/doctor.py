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

from . import APP_NAME, __version__, config


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
    for h, title, vis, area in cands:
        out += _line(f"   hwnd={h:<10} 보임={'예' if vis else '아니오(트레이)':<14} "
                     f"넓이={area:<10} 제목={title!r}")
    main = _safe(lambda: C.find_main_window(), None)
    out += _line(f"고른 본창          : {main}")
    if not main:
        out += _line("→ 창을 찾지 못했습니다. 브리티가 실행 중인지, "
                     "트레이에 숨어 있는지 확인이 필요합니다.")
        return out

    # 접근성 트리가 열리는지 (여기서 막히면 목록을 못 읽는다)
    try:
        import uiautomation as auto
        with auto.UIAutomationInitializerInThread():
            C.wake_accessibility(main)
            root = auto.ControlFromHandle(main)
            names, lists, total = [], 0, 0
            for x, _d in C._walk(root, maxdepth=12):
                total += 1
                try:
                    if x.ControlTypeName == "ListControl":
                        lists += 1
                    nm = (x.Name or "").strip()
                    if nm and len(names) < 12:
                        names.append(f"{x.ControlTypeName}:{nm[:24]}")
                except Exception:
                    continue
            out += _line(f"접근성 노드 수     : {total}")
            out += _line(f"목록(List) 컨트롤  : {lists}개")
            out += _line(f"보이는 이름 표본   : {names}")
            if total <= 1:
                out += _line("→ 접근성 트리가 비어 있습니다. 브리티가 로그인 화면이거나 "
                             "화면이 아직 그려지지 않았을 수 있습니다.")
    except Exception:
        out += _line("접근성 트리 확인 중 오류:\n" + traceback.format_exc())

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


def save_report() -> Path:
    """보고서를 바탕화면에 저장하고 경로를 돌려준다."""
    text = build_report()
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        desktop = Path.home() / "바탕 화면"
    if not desktop.exists():
        desktop = config.APP_DIR
    path = desktop / f"메움_진단_{datetime.now():%y%m%d_%H%M}.txt"
    path.write_text(text, encoding="utf-8", newline="\r\n")
    return path


def run_doctor(show: bool = True) -> int:
    path = save_report()
    if show:
        try:
            os.startfile(str(path))          # 메모장으로 열어 드린다
        except Exception:
            pass
    if sys.stdout is not None:
        try:
            print(f"진단 보고서를 저장했습니다:\n  {path}")
        except Exception:
            pass
    return 0
