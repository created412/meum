# -*- coding: utf-8 -*-
"""
쪽지를 '지켜보다가 조용할 때' 메운다.

하루 두 번 정해진 시각에 도는 방식은 두 가지가 아쉬웠다.
  · 그 시각에 메신저가 꺼져 있으면 그날 쪽지를 통째로 놓친다.
  · 정리하려면 브리티 창을 되살리고 '쪽지' 탭으로 바꿔야 해서,
    근무 중에 돌면 화면이 튄다.

그래서 **패널 프로세스 안에서 조용히 지켜보다가, 선생님이 자리를 비운 사이에**
정리한다. 부하가 큰 일(쪽지 열기)은 그때만 하고, 근무 중에는
창 목록만 훑는다 — EnumWindows 한 번은 1밀리초짜리라 체감 부하가 없다.

판단 기준
  강한 신호  GOE 쪽지 창이 새로 떴다 · 브리티 알림 창이 떴다 · 브리티가 방금 켜졌다
             → 새 쪽지가 확실하므로, 조용해지는 즉시 정리
  약한 신호  아무 신호도 없다
             → 자리를 비운 채 watch_idle_gap_min(기본 20분) 지나면 한 번 확인
  강제       마지막 정리 후 watch_max_gap_min(기본 120분)이 지나면
             자리에 계셔도 정리 (단 메신저를 쓰는 중이거나 발표 중이면 계속 미룸)

'조용하다'의 정의
  · 마지막 키보드·마우스 입력 후 watch_idle_sec(기본 45초)이 지났고
  · 지금 쓰고 있는 창이 브리티·GOE 가 아니며
  · 발표 모드·전체화면(수업 중)이 아니다

정리 도중 선생님이 돌아오시면 다음 쪽지로 넘어가지 않고 그 자리에서 멈춘다
(`user_is_back()` — 실제 판단은 정리를 맡은 자식 프로세스가 한다).
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Set

import win32gui
import win32process

from . import config

# 창 클래스 이름
BRITY_CLASS = "Chrome_WidgetWin_1"
GOE_NOTE_CLASS = "@Messenger7_Wnd"
GOE_MAIN_CLASS = "@Messenger7_MainWnd"

# SHQueryUserNotificationState 반환값 — 이때는 방해하지 않는다
QUNS_BUSY = 2                 # 전체화면 앱
QUNS_RUNNING_D3D_FULL_SCREEN = 3
QUNS_PRESENTATION_MODE = 4    # 발표 중 (수업!)
QUNS_QUIET_TIME = 6
BUSY_STATES = {QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE}


# ---------------------------------------------------------------------------
# 값싼 확인들 — 근무 중에도 부담 없이 부를 수 있는 것만 모았다
# ---------------------------------------------------------------------------
class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_seconds() -> float:
    """마지막 키보드·마우스 입력 이후 흐른 시간(초)."""
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        tick = ctypes.windll.kernel32.GetTickCount()
        return max(0.0, (tick - info.dwTime) / 1000.0)
    except Exception:
        return 0.0


def user_is_back(threshold: float = 5.0) -> bool:
    """선생님이 방금 자판을 만지셨는가 — 정리를 멈출지 판단할 때 쓴다."""
    return idle_seconds() < threshold


def presentation_mode() -> bool:
    """발표·전체화면(수업 중)인가."""
    try:
        st = wintypes.DWORD()
        ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(st))
        return st.value in BUSY_STATES
    except Exception:
        return False


def workstation_locked() -> bool:
    """
    잠금 화면인가.

    잠겨 있을 때는 건드리지 않는다. 창을 조작하는 방식이라 잠금 상태에서의
    동작을 이 프로그램이 놓일 모든 기종에서 확인할 수 없고, 실패하더라도
    선생님이 화면을 볼 수 없어 알아차릴 방법이 없기 때문이다.
    그 시간대는 아침·점심 보충 점검이 대신 맡는다.
    """
    try:
        user32 = ctypes.windll.user32
        h = user32.OpenInputDesktop(0, False, 0x0100)   # DESKTOP_SWITCHDESKTOP
        if not h:
            return True
        user32.CloseDesktop(h)
        return False
    except Exception:
        return False


def _pid_of(hwnd: int) -> int:
    try:
        return win32process.GetWindowThreadProcessId(hwnd)[1]
    except Exception:
        return 0


def scan_windows() -> dict:
    """
    창 목록을 한 번 훑어 필요한 것만 추린다.

    반환: {"brity": hwnd|None, "brity_pid": int, "goe_notes": {hwnd,...},
           "goe": hwnd|None, "brity_popups": {hwnd,...}}
    """
    found = {"brity": None, "brity_pid": 0, "goe": None,
             "goe_notes": set(), "chrome": []}

    def cb(h, _):
        if not win32gui.IsWindowVisible(h):
            return True
        cls = win32gui.GetClassName(h)
        if cls == GOE_NOTE_CLASS:
            found["goe_notes"].add(h)
        elif cls == GOE_MAIN_CLASS:
            found["goe"] = h
        elif cls == BRITY_CLASS:
            title = win32gui.GetWindowText(h)
            if title == "Brity Messenger":
                found["brity"] = h
                found["brity_pid"] = _pid_of(h)
            else:
                found["chrome"].append((h, title))
        return True

    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        pass

    # 브리티가 띄운 창 가운데 본창이 아닌 것 = 알림 토스트 · 쪽지 상세
    popups = set()
    pid = found["brity_pid"]
    if pid:
        for h, _title in found["chrome"]:
            if _pid_of(h) == pid:
                popups.add(h)
    found["brity_popups"] = popups
    found.pop("chrome", None)
    return found


def foreground_is_messenger(snap: dict) -> bool:
    """지금 쓰고 있는 창이 브리티나 GOE 인가 — 그렇다면 건드리지 않는다."""
    try:
        fg = win32gui.GetForegroundWindow()
        if not fg:
            return False
        if fg == snap.get("brity") or fg == snap.get("goe"):
            return True
        if fg in snap.get("goe_notes", ()) or fg in snap.get("brity_popups", ()):
            return True
        cls = win32gui.GetClassName(fg)
        if cls in (GOE_NOTE_CLASS, GOE_MAIN_CLASS):
            return True
        if cls == BRITY_CLASS and snap.get("brity_pid"):
            return _pid_of(fg) == snap["brity_pid"]
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# 감시 스레드
# ---------------------------------------------------------------------------
class Watcher:
    """
    패널 안에서 도는 감시 스레드.

    on_done(new_tasks: int, reason: str) 은 정리가 끝날 때마다 불린다.
    (tkinter 위젯을 직접 만지면 안 되므로, 받는 쪽에서 root.after 로 넘길 것)
    """

    def __init__(self, cfg: dict, on_done: Optional[Callable[[int, str], None]] = None,
                 log: Optional[Callable[[str], None]] = None,
                 count_tasks: Optional[Callable[[], int]] = None):
        self.cfg = cfg
        self.on_done = on_done
        self.log = log or (lambda *_: None)
        self.count_tasks = count_tasks
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._busy = False

        self._known_goe: Optional[Set[int]] = None      # 첫 바퀴는 '이미 있던 것'으로 본다
        self._known_popups: Optional[Set[int]] = None
        self._brity_seen = False
        self._goe_seen = False
        self._pending: Optional[str] = None             # 정리해야 할 이유 (대기 중)
        self._last_run: Optional[datetime] = None
        self._deferred_since: Optional[datetime] = None
        self._fails = 0                                 # 연달아 실패한 횟수
        self._idle_rounds = 0                           # 아무 일도 없던 점검 횟수
        self._quiet_until: Optional[float] = None       # 이 시각까지는 쉰다

    # -- 설정값 -------------------------------------------------------------
    @property
    def poll_sec(self) -> int:
        return max(5, int(self.cfg.get("watch_poll_sec", 20)))

    @property
    def idle_sec(self) -> int:
        return max(5, int(self.cfg.get("watch_idle_sec", 45)))

    @property
    def idle_gap_min(self) -> int:
        return max(1, int(self.cfg.get("watch_idle_gap_min", 20)))

    @property
    def max_gap_min(self) -> int:
        return max(0, int(self.cfg.get("watch_max_gap_min", 120)))

    # -- 수명 ---------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="meum-watcher")
        self._thread.start()
        self.log(f"감시 시작 (점검 {self.poll_sec}초 · 유휴 {self.idle_sec}초 "
                 f"· 조용할 때 {self.idle_gap_min}분마다 · 최대 {self.max_gap_min}분)")

    def stop(self) -> None:
        self._stop.set()

    # -- 본체 ---------------------------------------------------------------
    def _loop(self) -> None:
        # 켜자마자 달려들지 않는다. 로그인 직후는 브리티도 아직 뜨는 중이다.
        if self._stop.wait(25):
            return
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:                      # 감시가 죽으면 안 된다
                self.log(f"감시 오류(무시): {e}")
            if self._stop.wait(self._next_wait()):
                return

    def _next_wait(self) -> float:
        """
        다음 점검까지 얼마나 쉴까.

        메신저가 꺼져 있거나 실패가 이어지면 더 오래 쉰다.
        구형 노트북에서 쓸데없이 깨어나지 않게 하는 장치다.
        """
        base = self.poll_sec
        if self._idle_rounds > 6:        # 두어 분 동안 아무 일도 없었다
            base = min(base * 3, 120)
        return base

    def _tick(self) -> None:
        if self._busy or not self.cfg.get("watch_enabled", True):
            return

        # 실패가 이어지면 쉬어 간다 (5분 → 15 → 30 → 60분)
        if self._quiet_until and time.monotonic() < self._quiet_until:
            return

        snap = scan_windows()                            # ← 여기까지가 근무 중 부하 전부
        reason = self._pending or self._signal(snap)
        if not reason:
            self._idle_rounds += 1
            return
        self._idle_rounds = 0
        self._pending = reason
        if self._deferred_since is None:
            self._deferred_since = datetime.now()

        ok, why = self._quiet_enough(snap, reason)
        if not ok:
            return
        self.log(f"정리 시작 — {reason} ({why})")
        self._pending = None
        self._deferred_since = None
        self._run(reason)

    # -- 신호 판단 ----------------------------------------------------------
    def _signal(self, snap: dict) -> Optional[str]:
        goe_notes = snap["goe_notes"]
        popups = snap["brity_popups"]
        brity_up = snap["brity"] is not None

        goe_up = snap["goe"] is not None

        # 첫 바퀴: 지금 떠 있는 것들은 '새 쪽지'가 아니라 원래 있던 것으로 본다
        if self._known_goe is None:
            self._known_goe = set(goe_notes)
            self._known_popups = set(popups)
            self._brity_seen = brity_up
            self._goe_seen = goe_up
            return "첫 점검" if brity_up or goe_up else None

        reason = None
        if brity_up and not self._brity_seen:
            reason = "브리티가 켜졌습니다"
        elif goe_up and not self._goe_seen:
            reason = "GOE메신저가 켜졌습니다"
        elif goe_notes - self._known_goe:
            reason = "GOE 쪽지가 새로 왔습니다"
        elif popups - self._known_popups:
            reason = "브리티 알림이 떴습니다"

        self._known_goe = set(goe_notes)
        self._known_popups = set(popups)
        self._brity_seen = brity_up
        self._goe_seen = goe_up

        if reason:
            return reason
        if not (brity_up or goe_up):
            return None                                   # 메신저가 다 꺼져 있다

        since = self._minutes_since_run()
        if since is None or since >= self.idle_gap_min:
            return "정기 확인"
        return None

    def _minutes_since_run(self) -> Optional[float]:
        last = self._last_run
        if last is None:
            last = self._last_run_from_db()
        if last is None:
            return None
        return (datetime.now() - last).total_seconds() / 60.0

    def _last_run_from_db(self) -> Optional[datetime]:
        try:
            from .state import State
            st = State()
            try:
                return st.last_run_at
            finally:
                st.close()
        except Exception:
            return None

    # -- 지금 건드려도 되나 --------------------------------------------------
    def _quiet_enough(self, snap: dict, reason: str) -> tuple:
        if snap["brity"] is None and snap["goe"] is None:
            return False, "메신저가 꺼져 있음"
        if workstation_locked():
            return False, "잠금 화면"
        if presentation_mode():
            return False, "발표·전체화면 중"
        if foreground_is_messenger(snap):
            return False, "메신저를 쓰는 중"

        idle = idle_seconds()
        if idle >= self.idle_sec:
            return True, f"{int(idle)}초째 조용함"

        # 자리에 계셔도, 너무 오래 밀렸으면 한 번은 처리한다
        if self.max_gap_min:
            waited = self._minutes_since_run()
            if waited is not None and waited >= self.max_gap_min:
                return True, f"{int(waited)}분째 정리하지 못함"
        return False, "사용 중"

    # -- 실행 ---------------------------------------------------------------
    def _run(self, reason: str) -> None:
        self._busy = True

        def work():
            before = self._count()
            try:
                if getattr(sys, "frozen", False):
                    cmd = [sys.executable]
                else:
                    cmd = [sys.executable,
                           str(Path(__file__).resolve().parents[1] / "run.py")]
                cmd += ["--trigger", "watch", "--headless", "--force"]
                # 낮은 우선순위로 돌린다. 구형 노트북에서 선생님이 쓰시는 프로그램의
                # CPU 를 빼앗지 않도록 하는 장치다.
                flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                         | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
                r = subprocess.run(cmd, capture_output=True,
                                   creationflags=flags, timeout=15 * 60)
                if r.returncode == 0:
                    self._fails = 0
                    self._quiet_until = None
                else:
                    self._back_off(f"종료코드 {r.returncode}")
            except Exception as e:
                self._back_off(str(e))
            finally:
                self._last_run = datetime.now()
                self._busy = False
            added = max(0, self._count() - before)
            self.log(f"정리 끝 — 새 할 일 {added}건")
            if self.on_done:
                try:
                    self.on_done(added, reason)
                except Exception:
                    pass

        threading.Thread(target=work, daemon=True, name="meum-collect").start()

    def _back_off(self, why: str) -> None:
        """실패가 이어지면 점점 더 오래 쉰다 — 헛돌며 배터리를 먹지 않도록."""
        self._fails += 1
        minutes = (5, 15, 30, 60)[min(self._fails, 4) - 1]
        self._quiet_until = time.monotonic() + minutes * 60
        self.log(f"정리 실패({why}) — {minutes}분 뒤에 다시 시도합니다")

    def _count(self) -> int:
        if not self.count_tasks:
            return 0
        try:
            return int(self.count_tasks())
        except Exception:
            return 0
