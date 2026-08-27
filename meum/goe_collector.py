# -*- coding: utf-8 -*-
"""
GOE메신저(AtMessenger7) 수집기.

브리티와 다른 점
----------------
GOE메신저는 Electron 이 아니라 MFC 네이티브 앱이고, 목록을 직접 그리기 때문에
접근성 정보로 목록을 읽을 수 없다. 실측 결과는 이렇다.

  · 로컬 DB @Talk.db          → 암호화됨 (읽기 불가)
  · 받은 쪽지 '목록'           → UltariList 직접 그리기, 항목 0개 (읽기 불가)
  · 쪽지 '본문'                → RICHEDIT50W / EditControl.Value 로 전문 판독 가능
  · 제목·발신자·날짜·첨부파일명 → 직접 그리기 (읽기 불가)

그래서 이렇게 한다.
  1) 목록의 각 행 좌표에 클릭 메시지를 보내 쪽지를 연다
  2) 열린 창에서 본문 전문을 읽는다
  3) 창을 닫고 다음 행으로 내려간다
  4) 이미 본 쪽지(본문 해시가 같은 것)를 만나면 거기서 멈춘다
     — 받은 쪽지함은 최신순이므로, 그 아래는 전부 이미 본 것이다

발신자·제목은 본문에서 추정한다. 수신일시는 알 수 없어 수집 시각을 쓴다.
(그래서 '내일까지' 같은 상대 표현은 확신도를 낮춘다)
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Set

import win32api
import win32con
import win32gui
import uiautomation as auto

MAIN_CLASS = "@Messenger7_MainWnd"
NOTE_CLASS = "@Messenger7_Wnd"
LIST_CLASS = "UltariListScrollView"
MAIN_TITLE = "GOE메신저"

ROW_H = 66                # 실측한 행 높이
MAX_ROWS = 40             # 한 번에 훑어볼 최대 행 수
OPEN_TIMEOUT = 6.0

auto.SetGlobalSearchTimeout(3)

# GOE 인용부 머리글 — 여기에 원 발신자와 발신시간이 들어 있다
#   -------------------- 원본메시지 --------------------
#   발 신 자 : 박혜진 교사
#   발신시간 : 2026-08-25 오전 11:31
QUOTE_MARK = re.compile(r"-{5,}\s*원본\s*메시지\s*-{5,}")
_Q_SENDER = re.compile(r"발\s*신\s*자\s*:\s*([^\r\n]{1,30})")
_Q_TIME = re.compile(
    r"발신시간\s*:\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*(오전|오후)?\s*(\d{1,2}):(\d{2})")

# 본문에서 부서/발신자를 추정
_DEPT = re.compile(r"([가-힣]{2,10}(?:부|과|실|팀|위원회))에서")
_NAME_INTRO = re.compile(r"([가-힣]{2,10}(?:부|과|실|팀))\s*([가-힣]{2,4})\s*(?:입니다|드립니다)")
_SELF = re.compile(r"(?:안녕하세요[.,\s]*)?([가-힣]{2,4})\s*입니다")


class GoeError(RuntimeError):
    pass


class GoeNotRunning(GoeError):
    pass


@dataclass
class GoeNote:
    body: str
    sender: str = ""
    subject: str = ""
    collected_at: Optional[datetime] = None
    received_at: Optional[datetime] = None   # 인용부에서 알아낸 경우만
    row: int = -1

    @property
    def when(self) -> datetime:
        """마감일 계산의 기준일. 모르면 수집 시각으로 대신한다."""
        return self.received_at or self.collected_at or datetime.now()

    @property
    def key(self) -> str:
        """본문으로 만든 고유 키 — 같은 쪽지를 다시 열어도 같은 값."""
        norm = re.sub(r"\s+", " ", self.body).strip()
        return "goe-" + hashlib.sha1(norm.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
def _visible_notes() -> Set[int]:
    out = set()

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h) == NOTE_CLASS:
            out.add(h)
        return True

    win32gui.EnumWindows(cb, None)
    return out


def find_main() -> Optional[int]:
    found = []

    def cb(h, _):
        if win32gui.GetClassName(h) == MAIN_CLASS:
            found.append(h)
        return True

    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def is_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq AtMessengerMobileEdition.exe"],
            capture_output=True, text=True, errors="ignore").stdout
        return "AtMessengerMobileEdition" in out
    except Exception:
        return False


def normalize(body: str) -> str:
    """
    GOE 본문은 줄바꿈이 CR(캐리지 리턴) 이다.
    그대로 두면 추출기가 본문 전체를 한 줄로 보고
    문장·행 단위 처리가 모두 어긋난다. 반드시 LF 로 맞춘다.
    """
    if not body:
        return ""
    return body.replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))


def parse_quote_header(body: str):
    """인용부의 '발 신 자 / 발신시간' 을 읽는다. 없으면 (None, None)."""
    m = QUOTE_MARK.search(body)
    if not m:
        return None, None
    tail = body[m.end():m.end() + 400]
    sender = None
    ms = _Q_SENDER.search(tail)
    if ms:
        sender = ms.group(1).strip()
    when = None
    mt = _Q_TIME.search(tail)
    if mt:
        y, mo, d, ampm, hh, mi = mt.groups()
        hh = int(hh)
        if ampm == "오후" and hh < 12:
            hh += 12
        if ampm == "오전" and hh == 12:
            hh = 0
        try:
            when = datetime(int(y), int(mo), int(d), hh, int(mi))
        except ValueError:
            when = None
    return sender, when


def guess_sender(body: str) -> str:
    m = _NAME_INTRO.search(body)
    if m:
        return f"{m.group(2)}({m.group(1)})"
    m = _DEPT.search(body)
    if m:
        return m.group(1)
    m = _SELF.search(body)
    if m and len(m.group(1)) <= 4:
        return m.group(1)
    return ""


_TAG_ONLY = re.compile(r"^\[[^\]]{1,10}\]$")


def guess_subject(body: str) -> str:
    """
    첫 줄을 제목처럼 쓴다. GOE 쪽지는 '[안내] …' 로 시작하는 경우가 많은데
    '[안내]' 가 한 줄을 통째로 차지하기도 한다.
    그럴 때 다음 줄을 붙이지 않으면 제목이 '[안내]' 뿐인 쓸모없는 값이 된다.
    """
    lines = [l.strip() for l in body.split("\n") if l.strip()]
    if not lines:
        return re.sub(r"\s+", " ", body)[:60]
    first = lines[0]
    if (_TAG_ONLY.match(first) or len(first) < 5) and len(lines) > 1:
        return f"{first} {lines[1]}"[:80]
    return first[:80]


# --------------------------------------------------------------------------
class GoeCollector:
    def __init__(self, cfg: dict, log: Optional[Callable[[str], None]] = None):
        self.cfg = cfg
        self.log = log or (lambda s: None)
        self.hwnd: Optional[int] = None
        self.list_hwnd: Optional[int] = None
        self._restore_minimized = False
        # 마지막으로 훑을 때 '몇 번째 줄이 무슨 쪽지였는지' (collect 에서 채운다)
        self.last_order: List[str] = []

    @staticmethod
    def init_thread():
        return auto.UIAutomationInitializerInThread()

    # ---------- 준비 ----------
    def attach(self) -> None:
        if not is_running():
            raise GoeNotRunning("GOE메신저가 실행되고 있지 않습니다.")
        h = find_main()
        if not h:
            raise GoeNotRunning("GOE메신저 창을 찾지 못했습니다.")
        self.hwnd = h
        if win32gui.IsIconic(h):
            # 목록 좌표를 알아야 클릭할 수 있어 최소화 상태로는 못 읽는다.
            win32gui.ShowWindow(h, win32con.SW_SHOWNOACTIVATE)
            self._restore_minimized = True
            time.sleep(1.2)
            self.log("  · GOE메신저 창을 복원했습니다 (끝나면 되돌립니다)")
        self.list_hwnd = self._find_list()
        if not self.list_hwnd:
            raise GoeError("받은 쪽지 목록을 찾지 못했습니다. "
                           "GOE메신저에서 '쪽지함'을 열어 두세요.")
        self.log(f"GOE메신저 연결 (hwnd={h}, 목록={self.list_hwnd})")

    def _find_list(self) -> Optional[int]:
        """보이는 목록 중 가장 큰 것이 받은 쪽지 목록이다."""
        cands = []

        def cb(h, _):
            if win32gui.GetClassName(h) != LIST_CLASS:
                return True
            if not win32gui.IsWindowVisible(h):
                return True
            l, t, r, b = win32gui.GetWindowRect(h)
            cands.append((h, (l, t, r, b), (r - l) * (b - t)))
            return True

        win32gui.EnumChildWindows(self.hwnd, cb, None)
        if not cands:
            return None
        cands.sort(key=lambda x: -x[2])
        return cands[0][0]

    def restore(self) -> None:
        if self._restore_minimized and self.hwnd:
            try:
                win32gui.ShowWindow(self.hwnd, win32con.SW_MINIMIZE)
            except Exception:
                pass
            self._restore_minimized = False

    # ---------- 본문 ----------
    @staticmethod
    def _read_body(hwnd: int) -> str:
        try:
            w = auto.ControlFromHandle(hwnd)
        except Exception:
            return ""

        def walk(c, d=0):
            try:
                ch = c.GetChildren()
            except Exception:
                return
            for x in ch:
                yield x
                if d < 12:
                    yield from walk(x, d + 1)

        for x in walk(w):
            try:
                if x.ControlTypeName != "EditControl":
                    continue
                vp = x.GetValuePattern()
                if vp and (vp.Value or "").strip():
                    return vp.Value.strip()
            except Exception:
                continue
        return ""

    @staticmethod
    def _close(hwnd: int) -> None:
        try:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass

    def _click_row(self, y: int) -> bool:
        l, t, r, b = win32gui.GetWindowRect(self.list_hwnd)
        sx = l + (r - l) // 2
        try:
            lx, ly = win32gui.ScreenToClient(self.list_hwnd, (sx, y))
        except Exception:
            return False
        lp = win32api.MAKELONG(lx, ly)
        for msg, wp in ((win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON),
                        (win32con.WM_LBUTTONUP, 0),
                        (win32con.WM_LBUTTONDBLCLK, win32con.MK_LBUTTON),
                        (win32con.WM_LBUTTONUP, 0)):
            try:
                win32gui.PostMessage(self.list_hwnd, msg, wp, lp)
            except Exception:
                return False
            time.sleep(0.06)
        return True

    def _open_row(self, y: int) -> Optional[str]:
        """한 행을 열어 본문을 읽고 닫는다. 안 열리면 None."""
        before = _visible_notes()
        if not self._click_row(y):
            return None
        deadline = time.time() + OPEN_TIMEOUT
        opened = None
        while time.time() < deadline:
            time.sleep(0.35)
            new = _visible_notes() - before
            if new:
                opened = next(iter(new))
                break
        if not opened:
            return None
        time.sleep(0.9)
        body = self._read_body(opened)
        self._close(opened)
        # 창이 닫힐 때까지 잠깐 기다린다
        for _ in range(10):
            time.sleep(0.2)
            if opened not in _visible_notes():
                break
        return body or None

    # ---------- 수집 ----------
    def collect(self, known_keys: Set[str], max_rows: int = MAX_ROWS,
                progress: Optional[Callable[[int, str], None]] = None,
                should_stop: Optional[Callable[[], bool]] = None) -> List[GoeNote]:
        """
        위에서부터 훑다가 이미 본 쪽지를 **두 번 잇달아** 만나면 멈춘다.

        한 번만에 멈추면 구멍이 생긴다. 수집이 중간에 끊긴 다음 실행에서는
        맨 윗줄이 '이미 본 쪽지'라 곧바로 멈춰 버려, 그 아래에서 못 읽은
        쪽지들이 영영 수집되지 않기 때문이다. 한 줄 더 보는 값으로 막는다.

        훑으면서 '몇 번째 줄이 무슨 쪽지인지'를 self.last_order 에 남긴다.
        목록을 읽을 수 없는 GOE 에서, 나중에 그 쪽지를 다시 띄울 때
        어느 줄을 눌러야 하는지 아는 유일한 단서다(reopen.py).
        """
        l, t, r, b = win32gui.GetWindowRect(self.list_hwnd)
        out: List[GoeNote] = []
        seen_now: Set[str] = set()
        self.last_order: List[str] = []
        known_streak = 0
        misses = 0

        for row in range(max_rows):
            y = t + 30 + row * ROW_H
            if y > b - 10:
                break
            if should_stop and row and should_stop():
                self.log("  · 선생님이 자리에 돌아오셔서 여기까지만 확인했습니다")
                break
            if progress:
                progress(row, f"GOE 쪽지 {row + 1}번째 확인 중")

            body = self._open_row(y)
            if not body:
                misses += 1
                # 연속으로 두 번 안 열리면 목록 끝으로 본다
                if misses >= 2 and out:
                    break
                continue
            misses = 0

            body = normalize(body)
            note = GoeNote(body=body, collected_at=datetime.now(), row=row)
            q_sender, q_time = parse_quote_header(body)
            # 전달된 쪽지면 원 발신자·발신시간이 그대로 들어 있다
            note.sender = q_sender or guess_sender(body)
            note.received_at = q_time
            note.subject = guess_subject(body)

            if note.key in seen_now:
                continue                      # 같은 창이 다시 잡힌 경우
            seen_now.add(note.key)
            self.last_order.append(note.key)  # 몇 번째 줄이 무슨 쪽지였는지

            if note.key in known_keys:
                known_streak += 1
                if known_streak >= 2:
                    self.log(f"  · 이미 본 쪽지가 이어져 중단 ({row + 1}번째)")
                    break
                continue
            known_streak = 0

            out.append(note)
            self.log(f"  + GOE: {note.subject[:34]}")

        self.log(f"GOE 신규 {len(out)}건")
        return out
