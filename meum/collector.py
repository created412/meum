# -*- coding: utf-8 -*-
"""
브리티 메신저 UI Automation 수집기.

0단계 실측(2026-08-21)으로 검증된 경로:
  · 로컬 DB는 암호화되어 있어 사용 불가
  · Chromium 접근성 엔진을 WM_GETOBJECT 로 깨우면 트리가 노출됨
  · 창이 최소화/백그라운드여도 판독 가능
  · 표준 InvokePattern 은 무반응 → 좌표 더블클릭으로 상세 창을 연다

원칙: 열기(더블클릭)와 닫기(WM_CLOSE) 외의 조작은 구현하지 않는다.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

import win32api
import win32con
import win32gui
import win32process
import uiautomation as auto

OBJID_CLIENT = 0xFFFFFFFC
MAIN_TITLE = "Brity Messenger"
DETAIL_TITLE = "쪽지"
WIDGET_CLASS = "Chrome_WidgetWin_1"
RENDER_CLASS = "Chrome_RenderWidgetHostHWND"

DT_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})\b")
MMDD_RE = re.compile(r"^(\d{1,2})-(\d{1,2})$")
HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
KOR_MD_RE = re.compile(r"^(\d{1,2})\s*월\s*(\d{1,2})\s*일$")

auto.SetGlobalSearchTimeout(3)


# --------------------------------------------------------------------------
# 자료 구조
# --------------------------------------------------------------------------
@dataclass
class ListedNote:
    """쪽지함 목록에서 읽어낸 한 줄."""
    preview: str
    sender: str
    date_text: str
    has_attach: bool
    approx_dt: Optional[datetime]
    rect: tuple  # (l, t, r, b)

    @property
    def list_key(self) -> str:
        # 날짜 표기가 '08-20' 과 '8월 20일' 두 형태로 오므로 정규화해서 쓴다.
        # (원문을 그대로 쓰면 같은 쪽지를 두 번 수집한다)
        day = self.approx_dt.date().isoformat() if self.approx_dt else self.date_text
        raw = f"{day}|{self.sender}|{self.preview[:60]}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class NoteDetail:
    """상세 창에서 읽어낸 쪽지 전문."""
    subject: str = ""
    sender: str = ""
    sender_org: str = ""
    received_at: Optional[datetime] = None
    body: str = ""
    attachments: list = field(default_factory=list)

    @property
    def msg_id(self) -> str:
        base = f"{self.received_at.isoformat() if self.received_at else ''}|{self.sender}|{self.subject[:60]}"
        return hashlib.sha1(base.encode("utf-8")).hexdigest()


class CollectorError(RuntimeError):
    pass


class NotSignedInError(CollectorError):
    """브리티에 로그인되어 있지 않은 상태. 부팅 직후 09:00 실행에서 흔히 발생한다."""
    pass


# --------------------------------------------------------------------------
# 윈도우 유틸
# --------------------------------------------------------------------------
def _visible_widget_windows() -> list:
    res = []

    def cb(h, _):
        if win32gui.GetClassName(h) == WIDGET_CLASS and win32gui.IsWindowVisible(h):
            res.append((h, win32gui.GetWindowText(h)))
        return True

    win32gui.EnumWindows(cb, None)
    return res


def brity_pids() -> set:
    """
    브리티 프로세스의 PID.

    실행 파일 이름을 정확히 맞추지 않는다. 학교마다 버전이 달라
    'BrityMessenger.exe' 가 아닐 수 있기 때문이다.
    """
    pids = set()
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, errors="ignore").stdout
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and "brity" in parts[0].lower():
                try:
                    pids.add(int(parts[1]))
                except ValueError:
                    continue
    except Exception:
        pass
    return pids


def _has_renderer(hwnd: int) -> bool:
    """내용을 그리는 자식 창이 달려 있는가 — 진짜 화면 창인지 가리는 기준."""
    found = []
    try:
        win32gui.EnumChildWindows(
            hwnd,
            lambda h, _: (found.append(h)
                          if win32gui.GetClassName(h) == RENDER_CLASS else None,
                          not found)[-1],
            None)
    except Exception:
        pass
    return bool(found)


def brity_windows() -> list:
    """
    브리티가 가진 창 후보들. [(hwnd, 제목, 보임, 넓이)] 를 넓은 순으로.

    제목이 정확히 'Brity Messenger' 인 보이는 창만 찾던 때에는,
    다른 선생님 PC 에서 브리티를 켜 두셨는데도 '연결 안 됨' 이 떴다.
      · 트레이로 내려놓으면 창이 '보이지 않는' 상태가 된다
      · 버전에 따라 제목이 다를 수 있다
    그래서 **프로세스로** 찾고, 숨은 창도 후보에 넣는다.
    """
    pids = brity_pids()
    out = []

    def cb(h, _):
        try:
            if win32gui.GetClassName(h) != WIDGET_CLASS:
                return True
            if pids:
                _, pid = win32process.GetWindowThreadProcessId(h)
                if pid not in pids:
                    return True
            elif not _looks_like_main(win32gui.GetWindowText(h)):
                # 브리티 프로세스를 못 찾은 경우에는 제목이라도 맞아야 한다.
                # 그러지 않으면 Chrome·Electron 으로 만든 다른 프로그램의 창을
                # 브리티로 착각한다(실측: 메뉴가 '파일/편집/보기'인 엉뚱한 창).
                return True
            l, t, r, b = win32gui.GetWindowRect(h)
            w, ht = r - l, b - t
            if w < 200 or ht < 200:          # 풍선 도움말 따위는 거른다
                return True
            if not _has_renderer(h):
                return True
            out.append((h, win32gui.GetWindowText(h),
                        bool(win32gui.IsWindowVisible(h)), w * ht))
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    out.sort(key=lambda x: x[3], reverse=True)
    return out


def _looks_like_main(title: str) -> bool:
    """본창다운 제목인가. 버전·언어가 달라도 걸리도록 넉넉히 본다."""
    raw = title or ""
    t = raw.lower()
    return ("brity" in t) or ("messenger" in t) or ("메신저" in raw)


def find_main_window(allow_hidden: bool = True) -> Optional[int]:
    """
    브리티 본창을 찾는다.

    제목이 딱 맞는 보이는 창 → 제목이 본창다운 창 → (그것도 없으면)
    제목 없는 가장 큰 창 순으로 보고, 그래도 없으면 숨어 있는
    (트레이로 내려놓은) 창까지 본다.

    브리티는 'Opener' 같은 숨은 보조 창도 갖고 있어서, 무턱대고 '가장 큰
    창'을 고르면 엉뚱한 창을 잡는다. 그래서 제목을 먼저 본다.
    """
    cands = brity_windows()
    if not cands:
        return None

    for want_visible in (True, False):
        if not want_visible and not allow_hidden:
            break
        pool = [c for c in cands if c[2] == want_visible]
        for h, t, _v, _a in pool:
            if t == MAIN_TITLE:
                return h
        for h, t, _v, _a in pool:
            if _looks_like_main(t):
                return h
        untitled = [c for c in pool if not (c[1] or "").strip()]
        if untitled:
            return untitled[0][0]
    return None


def window_is_app(hwnd: int) -> bool:
    """
    이 창이 브리티 '본창'인가 — 제목이 아니라 **안에 든 것**으로 가린다.

    브리티는 알림 팝업 창에도 'Brity Messenger' 라는 같은 제목을 붙인다.
    그래서 제목만 보고 고르면, 본창을 닫아 트레이에 두신 분의 컴퓨터에서는
    알림 창을 본창으로 착각해 '쪽지 목록을 찾지 못했습니다' 로 끝난다
    (실제로 다른 선생님 PC 에서 이 증상이 나왔다. 그 창 안에는 '알림 끄기',
    '항상 위' 단추만 있고 쪽지 목록이 없었다).

    본창에는 쪽지 목록(ListControl)이나 '쪽지' 이동 단추가 반드시 있다.
    """
    try:
        wake_accessibility(hwnd)
        root = auto.ControlFromHandle(hwnd)
        if root is None:
            return False

        hit = False
        for x, _d in _walk(root, maxdepth=12):
            try:
                ct = x.ControlTypeName
                nm = (x.Name or "").strip()
            except Exception:
                continue

            # 알림 팝업에만 있는 것들 — 보이면 본창이 아니다
            if ct == "ButtonControl" and nm in ("알림 끄기", "항상 위"):
                return False

            if ct == "ListControl":
                hit = True
            elif ct == "ButtonControl" and nm in ("쪽지", "로그인"):
                # '로그인' 이면 로그인 화면이지만 그래도 본창이다.
                # (로그인이 필요하다는 안내는 _assert_signed_in 이 따로 해 준다)
                hit = True
            elif ct == "TabItemControl" and nm in ("받은 쪽지함", "보낸 쪽지함"):
                hit = True
            elif ct == "GroupControl" and nm in ("GNB", "Top menu"):
                hit = True
        return hit
    except Exception:
        return False


def find_app_window() -> Optional[int]:
    """쪽지를 읽을 수 있는 진짜 본창을 고른다. 없으면 None."""
    for h, _t, _v, _a in brity_windows():
        if window_is_app(h):
            return h
    return None


def wake_accessibility(hwnd: int) -> None:
    """Chromium 접근성 엔진 활성화. 이걸 보내지 않으면 트리가 비어 있다."""
    handles = [hwnd]
    try:
        win32gui.EnumChildWindows(
            hwnd,
            lambda h, _: (handles.append(h)
                          if win32gui.GetClassName(h) == RENDER_CLASS else None, True)[-1],
            None,
        )
    except Exception:
        pass
    for h in handles:
        try:
            win32gui.SendMessage(h, win32con.WM_GETOBJECT, 0, OBJID_CLIENT)
        except Exception:
            pass


def brity_is_running() -> bool:
    """실행 파일 이름이 학교마다 다를 수 있어 'brity' 가 들어가면 인정한다."""
    return bool(brity_pids())


def _running_exe_path() -> Optional[Path]:
    """이미 돌고 있는 브리티의 실행 파일 경로를 프로세스에서 직접 알아낸다."""
    import ctypes
    from ctypes import wintypes
    for pid in brity_pids():
        h = None
        try:
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # LIMITED_INFO
            if not h:
                continue
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                    h, 0, buf, ctypes.byref(size)):
                p = Path(buf.value)
                if p.exists():
                    return p
        except Exception:
            continue
        finally:
            if h:
                try:
                    ctypes.windll.kernel32.CloseHandle(h)
                except Exception:
                    pass
    return None


def find_brity_exe() -> Optional[Path]:
    """
    브리티 실행 파일 찾기.

    학교 PC 마다 설치 위치가 다르다. 삼성 폴더만 뒤지면 못 찾는 컴퓨터가
    나오므로, 돌고 있는 프로세스 → 흔한 설치 경로 → 시작 메뉴 바로가기
    순으로 넓게 찾는다.
    """
    p = _running_exe_path()
    if p:
        return p

    roots = [
        Path(r"C:\Program Files\Samsung"),
        Path(r"C:\Program Files (x86)\Samsung"),
        Path(r"C:\Program Files"),
        Path(r"C:\Program Files (x86)"),
    ]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.insert(0, Path(local) / "Programs")
        roots.insert(1, Path(local))
    for root in roots:
        try:
            if not root.exists():
                continue
            # 통째로 뒤지면 느리므로 브리티로 보이는 폴더만 본다
            for d in root.iterdir():
                if not d.is_dir() or "brity" not in d.name.lower():
                    continue
                for f in d.rglob("*.exe"):
                    if "brity" in f.name.lower():
                        return f
        except Exception:
            continue

    # 시작 메뉴 바로가기가 가리키는 곳
    try:
        import win32com.client
        sh = win32com.client.Dispatch("WScript.Shell")
        menus = [Path(os.environ.get("ProgramData", "")) / r"Microsoft\Windows\Start Menu",
                 Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu"]
        for m in menus:
            if not m.exists():
                continue
            for lnk in m.rglob("*.lnk"):
                if "brity" not in lnk.stem.lower():
                    continue
                target = Path(sh.CreateShortcut(str(lnk)).TargetPath)
                if target.exists():
                    return target
    except Exception:
        pass
    return None


def ensure_brity(launch: bool = True, timeout: float = 60.0) -> int:
    """
    쪽지를 읽을 수 있는 브리티 본창을 확보한다.

    브리티는 창을 닫아도 트레이에 남아 계속 돌아간다. 그 상태에서는
    '본창'이 아예 없고 알림 팝업 창만 있는데, 제목이 본창과 똑같아서
    예전에는 그 창을 붙잡고 '쪽지 목록을 찾지 못했습니다' 로 끝났다.

    그래서 창의 **내용**으로 본창을 가리고(window_is_app), 본창이 없으면
    실행 파일을 한 번 더 실행해 브리티에게 창을 열어 달라고 한다.
    (브리티는 두 번 실행하면 새 창을 띄우는 대신 이미 떠 있는 자신의
     창을 보여 준다 — 그래서 숨은 'Opener' 창을 갖고 있다)
    """
    h = find_app_window()
    if h:
        return h

    running = brity_is_running()
    if not launch:
        raise CollectorError(
            "브리티 메신저 창이 열려 있지 않습니다."
            if running else "브리티 메신저가 실행되고 있지 않습니다.")

    exe = find_brity_exe()
    if not exe:
        raise CollectorError(
            "브리티 메신저 실행 파일을 찾지 못했습니다.\n"
            "브리티를 실행한 뒤 다시 시도해 주세요.")
    try:
        subprocess.Popen([str(exe)], close_fds=True)
    except Exception as e:
        raise CollectorError(f"브리티 메신저를 실행하지 못했습니다: {e}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        h = find_app_window()
        if h:
            time.sleep(3)  # 로그인/렌더 대기
            return h
    raise CollectorError(
        "브리티 메신저 창을 열지 못했습니다.\n"
        "브리티가 트레이(화면 오른쪽 아래 시계 옆)에 있다면 그 아이콘을 눌러\n"
        "창을 띄워 두신 뒤 다시 시도해 주세요."
        if running else "브리티 메신저를 실행했지만 창이 열리지 않았습니다.")


# --------------------------------------------------------------------------
# 트리 탐색 유틸
# --------------------------------------------------------------------------
def _walk(ctrl, maxdepth=30):
    """
    전위 순회(DFS). 화면에 보이는 순서 = 문서 순서로 노드를 돌려준다.

    주의: 너비 우선으로 돌면 깊이가 얕은 노드가 먼저 나와
          목록의 '날짜'가 '제목'보다 앞서고 본문 줄 순서도 뒤집힌다.
    """
    def rec(c, d):
        if d > maxdepth:
            return
        try:
            children = c.GetChildren()
        except Exception:
            return
        for x in children:
            yield x, d
            yield from rec(x, d + 1)

    yield from rec(ctrl, 0)


def _find_first(ctrl, pred, maxdepth=30):
    for x, _ in _walk(ctrl, maxdepth):
        try:
            if pred(x):
                return x
        except Exception:
            continue
    return None


def _find_all(ctrl, pred, maxdepth=30):
    out = []
    for x, _ in _walk(ctrl, maxdepth):
        try:
            if pred(x):
                out.append(x)
        except Exception:
            continue
    return out


def _name(x) -> str:
    try:
        return (x.Name or "").strip()
    except Exception:
        return ""


# --------------------------------------------------------------------------
# 날짜 해석
# --------------------------------------------------------------------------
def parse_list_date(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """목록의 날짜 표기('08-20', '13:15', '어제')를 대략적인 일시로 바꾼다."""
    now = now or datetime.now()
    text = (text or "").strip()
    m = MMDD_RE.match(text)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        year = now.year
        try:
            dt = datetime(year, mm, dd)
        except ValueError:
            return None
        # 미래 날짜로 나오면 작년 것
        if dt.date() > now.date() + timedelta(days=1):
            dt = dt.replace(year=year - 1)
        return dt
    m = KOR_MD_RE.match(text)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        try:
            dt = datetime(now.year, mm, dd)
        except ValueError:
            return None
        if dt.date() > now.date() + timedelta(days=1):
            dt = dt.replace(year=now.year - 1)
        return dt
    m = HHMM_RE.match(text)
    if m:
        return now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                           second=0, microsecond=0)
    if "어제" in text:
        return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if "오늘" in text:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return None


# --------------------------------------------------------------------------
# 수집기
# --------------------------------------------------------------------------
class BrityCollector:
    def __init__(self, cfg: dict, log: Optional[Callable[[str], None]] = None):
        self.cfg = cfg
        self.log = log or (lambda s: None)
        self.hwnd: Optional[int] = None
        self._saved_cursor = None
        self._was_iconic = False
        self._was_hidden = False

    # ---------- 준비 ----------
    @staticmethod
    def init_thread():
        """
        작업 스레드에서 UI Automation 을 쓰려면 COM 을 먼저 초기화해야 한다.
        (설치 마법사처럼 화면이 멈추지 않도록 별도 스레드에서 돌릴 때 필요)

        with BrityCollector.init_thread():
            ...
        """
        return auto.UIAutomationInitializerInThread()

    def attach(self) -> None:
        self.hwnd = ensure_brity(launch=self.cfg.get("launch_brity_if_closed", True))
        try:
            self._was_iconic = bool(win32gui.IsIconic(self.hwnd))
            # 트레이로 내려놓으면 '보이지 않는 창'이 된다.
            # 끝나면 있던 그대로 되돌려 놓아야 한다.
            self._was_hidden = not bool(win32gui.IsWindowVisible(self.hwnd))
        except Exception:
            self._was_iconic = False
            self._was_hidden = False
        wake_accessibility(self.hwnd)
        time.sleep(1.5)
        state = (" (트레이 상태)" if self._was_hidden
                 else " (최소화 상태)" if self._was_iconic else "")
        self.log(f"브리티 창 연결 (hwnd={self.hwnd}){state}")

    def ensure_restored(self) -> bool:
        """
        본문을 열려면 창이 화면에 있어야 한다.

        목록 '판독'은 최소화 상태에서도 되지만, 창을 클릭해 상세 창을 여는 것은
        최소화 상태에서 좌표가 무의미해져 실패한다(실측 확인).
        트레이로 내려놓아 아예 숨어 있는 경우도 마찬가지다.
        따라서 포커스는 뺏지 않고(SW_SHOWNOACTIVATE) 화면에만 되살린다.
        """
        try:
            hidden = not win32gui.IsWindowVisible(self.hwnd)
            if not hidden and not win32gui.IsIconic(self.hwnd):
                return True
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
            time.sleep(1.2)
            wake_accessibility(self.hwnd)
            time.sleep(0.8)
            ok = (win32gui.IsWindowVisible(self.hwnd)
                  and not win32gui.IsIconic(self.hwnd))
            self.log("  · 본문 열람을 위해 브리티 창을 되살렸습니다"
                     f"{'' if ok else ' (실패)'}")
            return ok
        except Exception:
            return False

    def _root(self):
        wake_accessibility(self.hwnd)
        return auto.ControlFromHandle(self.hwnd)

    def detect_my_name(self) -> str:
        """GNB 아바타의 이름(로그인 사용자)을 읽는다."""
        try:
            root = self._root()
            gnb = _find_first(root, lambda x: x.ControlTypeName == "GroupControl"
                              and _name(x) == "GNB")
            if gnb:
                img = _find_first(gnb, lambda x: x.ControlTypeName == "ImageControl"
                                  and _name(x))
                if img:
                    return _name(img)
        except Exception:
            pass
        return ""

    def _assert_signed_in(self) -> None:
        """
        로그인 화면이면 즉시 멈춘다.

        이 상태를 그냥 두면 '목록을 찾지 못했습니다' 같은 엉뚱한 오류로 보여서
        원인을 못 찾는다. 실제로 세션이 끊겨 전체 실행이 실패한 사례가 있었다.
        """
        try:
            root = self._root()
        except Exception:
            return
        for x, _ in _walk(root, maxdepth=25):
            try:
                nm = _name(x)
                ct = x.ControlTypeName
            except Exception:
                continue
            if not nm:
                continue
            if "서버 연결에 실패" in nm or "접속 정보를 가져올 수 없" in nm:
                raise NotSignedInError(
                    "브리티 메신저가 서버에 연결되어 있지 않습니다.\n"
                    "브리티에서 다시 로그인한 뒤 실행해 주세요.")
            if ct == "ButtonControl" and nm == "로그인":
                raise NotSignedInError(
                    "브리티 메신저에 로그인되어 있지 않습니다.\n"
                    "브리티에서 로그인한 뒤 실행해 주세요.")

    def _ensure_note_tab(self) -> None:
        """'쪽지' 화면 + '받은 쪽지함' 탭 상태로 맞춘다."""
        root = self._root()
        lst = _find_first(root, lambda x: x.ControlTypeName == "ListControl")
        if lst is None:
            btn = _find_first(root, lambda x: x.ControlTypeName == "ButtonControl"
                              and _name(x) == "쪽지")
            if btn is not None:
                r = btn.BoundingRectangle
                self._click(r.left + (r.right - r.left) // 2,
                            r.top + (r.bottom - r.top) // 2)
                time.sleep(1.5)
                root = self._root()

        tab = _find_first(root, lambda x: x.ControlTypeName == "TabItemControl"
                          and _name(x) == "받은 쪽지함")
        if tab is not None:
            selected = True
            try:
                selected = tab.GetSelectionItemPattern().IsSelected
            except Exception:
                pass
            if not selected:
                r = tab.BoundingRectangle
                self._click(r.left + (r.right - r.left) // 2,
                            r.top + (r.bottom - r.top) // 2)
                time.sleep(1.2)

    # ---------- 목록 ----------
    def list_notes(self, scroll_rounds: int = 3) -> list:
        """받은 쪽지함 목록을 읽는다."""
        # 최소화 상태에서도 '읽기'는 되지만, 탭 전환·목록 탐색까지 포함한
        # 실제 흐름에서는 트리가 비어 나오는 경우가 있어 먼저 복원한다.
        # (포커스는 뺏지 않으며, 끝나면 restore() 에서 원래대로 되돌린다)
        self.ensure_restored()
        self._assert_signed_in()
        self._ensure_note_tab()

        lst = None
        for attempt in range(3):
            root = self._root()
            lst = _find_first(root, lambda x: x.ControlTypeName == "ListControl")
            if lst is not None:
                break
            self._assert_signed_in()
            time.sleep(1.5)
        if lst is None:
            raise CollectorError("쪽지 목록을 찾지 못했습니다. "
                                 "브리티 화면이 '쪽지' 탭인지 확인해 주세요.")

        seen: dict = {}
        scrolled = 0
        for round_i in range(max(1, scroll_rounds)):
            for item in _find_all(lst, lambda x: x.ControlTypeName == "ListItemControl", maxdepth=6):
                note = self._parse_list_item(item)
                if note and note.list_key not in seen:
                    seen[note.list_key] = note
            if round_i < scroll_rounds - 1:
                if not self._scroll(lst, down=True, times=4):
                    break
                time.sleep(0.6)
                scrolled += 4

        # 스크롤했다면 맨 위로 되돌린다.
        # (이후 쪽지를 열 때 화면 밖으로 나간 항목은 찾을 수 없기 때문)
        if scrolled:
            self._scroll(lst, down=False, times=scrolled + 4)
            time.sleep(0.6)

        notes = list(seen.values())
        self.log(f"목록 {len(notes)}건 수집")
        return notes

    def _scroll(self, ctrl, down: bool = True, times: int = 3) -> bool:
        """실제 휠 대신 창에 WM_MOUSEWHEEL 을 보낸다(가려져 있어도 동작)."""
        rh = self._renderer(self.hwnd)
        if rh is None:
            return False
        try:
            r = ctrl.BoundingRectangle
            sx = r.left + (r.right - r.left) // 2
            sy = r.top + (r.bottom - r.top) // 2
        except Exception:
            return False
        # WM_MOUSEWHEEL 의 lParam 은 화면 좌표를 쓴다
        lp = win32api.MAKELONG(int(sx), int(sy))
        delta = -120 if down else 120
        wp = (delta << 16) & 0xFFFFFFFF   # 상위 워드가 휠 델타(부호 있음)
        for _ in range(max(1, times)):
            try:
                win32gui.PostMessage(rh, win32con.WM_MOUSEWHEEL, wp, lp)
            except Exception:
                return False
            time.sleep(0.12)
        return True

    def _parse_list_item(self, item) -> Optional[ListedNote]:
        texts = [_name(x) for x, _ in _walk(item, maxdepth=6)
                 if x.ControlTypeName == "TextControl" and _name(x)]
        full = _name(item)
        if not texts and not full:
            return None

        # 순서에만 기대지 않고 형태로 분류한다.
        #   날짜  : '08-20' 또는 '13:15'
        #   발신자: 짧은 텍스트(사람 이름)
        #   제목  : 남은 것 중 가장 긴 텍스트
        date_text = next((t for t in texts
                          if MMDD_RE.match(t) or HHMM_RE.match(t)), "")
        rest = [t for t in texts if t != date_text]
        preview = max(rest, key=len) if rest else ""
        others = [t for t in rest if t is not preview and len(t) <= 12]
        sender = others[-1] if others else ""

        # 날짜 텍스트가 렌더되지 않는 행이 실제로 있다(실측).
        # 그때는 항목 이름("제목, 발신자, 첨부파일, 8월 20일")에서 뽑는다.
        if not date_text and full:
            parts = [p.strip() for p in full.split(",")]
            parts = [p for p in parts if p and p != "첨부파일"]
            if parts:
                date_text = parts[-1]
                if not sender and len(parts) >= 2:
                    sender = parts[-2]
        if not preview and full:
            preview = full.split(",")[0].strip()
        if not preview:
            return None
        has_attach = "첨부파일" in full
        try:
            r = item.BoundingRectangle
            rect = (r.left, r.top, r.right, r.bottom)
        except Exception:
            rect = (0, 0, 0, 0)
        return ListedNote(
            preview=preview, sender=sender, date_text=date_text,
            has_attach=has_attach, approx_dt=parse_list_date(date_text), rect=rect,
        )

    # ---------- 상세 ----------
    def _current_rect(self, note: ListedNote) -> Optional[tuple]:
        """목록에서 해당 쪽지의 현재 화면 위치를 다시 찾는다."""
        try:
            root = self._root()
            lst = _find_first(root, lambda x: x.ControlTypeName == "ListControl")
            if lst is None:
                return None
            for item in _find_all(lst, lambda x: x.ControlTypeName == "ListItemControl",
                                  maxdepth=6):
                cur = self._parse_list_item(item)
                if cur and cur.list_key == note.list_key:
                    return cur.rect
        except Exception:
            pass
        return None

    def open_and_read(self, note: ListedNote, timeout: float = 12.0,
                      attempts: int = 2) -> Optional[NoteDetail]:
        """쪽지를 열어 본문 전문을 읽고 창을 닫는다. 실패하면 한 번 더 시도한다."""
        for i in range(max(1, attempts)):
            d = self._open_once(note, timeout)
            if d:
                return d
            if i + 1 < attempts:
                self.log(f"  · 재시도: {note.preview[:26]}")
                self._wait_no_detail()
                time.sleep(1.2)
        self.log(f"  ! 본문 판독 실패: {note.preview[:30]}")
        return None

    def _wait_no_detail(self, timeout: float = 4.0) -> None:
        """열려 있는 상세 창이 완전히 닫힐 때까지 기다린다."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not any(t == DETAIL_TITLE for _, t in _visible_widget_windows()):
                return
            time.sleep(0.3)

    def _open_once(self, note: ListedNote, timeout: float) -> Optional[NoteDetail]:
        if not self.ensure_restored():
            return None
        self._wait_no_detail()
        before = {h for h, _ in _visible_widget_windows()}

        # 목록이 스크롤·갱신되었을 수 있으므로 클릭 직전에 좌표를 다시 구한다.
        rect = self._current_rect(note) or note.rect
        l, t, r, b = rect
        if r - l <= 0:
            return None
        cx, cy = l + (r - l) // 2, t + (b - t) // 2

        if not self._click(cx, cy, double=True):
            return None

        detail_hwnd = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            new = {h for h, _ in _visible_widget_windows()} - before
            for h in new:
                wake_accessibility(h)
                detail_hwnd = h
            if detail_hwnd and win32gui.IsWindow(detail_hwnd):
                time.sleep(1.0)
                wake_accessibility(detail_hwnd)
                detail = self._read_detail(detail_hwnd)
                if detail and detail.body:
                    self._close(detail_hwnd)
                    return detail
            time.sleep(0.4)

        if detail_hwnd:
            self._close(detail_hwnd)
        return None

    def _read_detail(self, hwnd: int) -> Optional[NoteDetail]:
        try:
            w = auto.ControlFromHandle(hwnd)
        except Exception:
            return None

        nodes = []
        for x, _ in _walk(w, maxdepth=30):
            nm = _name(x)
            if nm:
                nodes.append((x.ControlTypeName, nm))
        if len(nodes) < 4:
            return None

        d = NoteDetail()

        # 수신일시
        for ct, nm in nodes:
            m = DT_RE.search(nm)
            if m and ct == "TextControl":
                try:
                    d.received_at = datetime(int(m.group(1)), int(m.group(2)),
                                             int(m.group(3)), int(m.group(4)), int(m.group(5)))
                    break
                except ValueError:
                    pass

        # 본문: 가장 긴 DocumentControl 이 본문 전체를 담고 있다
        docs = [nm for ct, nm in nodes if ct == "DocumentControl" and nm != DETAIL_TITLE]
        body_lines = []
        if docs:
            longest = max(docs, key=len)
            # 본문 영역의 TextControl 들을 줄 단위로 모은다 (줄바꿈 보존)
            idx = next((i for i, (ct, nm) in enumerate(nodes)
                        if ct == "DocumentControl" and nm == longest), None)
            if idx is not None:
                for ct, nm in nodes[idx + 1:]:
                    if ct == "TextControl" and nm:
                        body_lines.append(nm)
            if not body_lines:
                body_lines = [longest]
        if not body_lines:
            texts = [nm for ct, nm in nodes if ct == "TextControl" and len(nm) > 25]
            body_lines = texts[-5:] if texts else []
        d.body = "\n".join(body_lines).strip()

        # 발신자 / 소속
        #   화면 구조는 [제목] [아바타 이미지=이름] [이름] [소속] [수신일시] 순이다.
        #   수신일시 앞의 텍스트를 그냥 집으면 제목이 발신자로 잡히므로
        #   아바타 이미지의 이름을 기준점으로 삼는다.
        dt_idx = next((i for i, (ct, nm) in enumerate(nodes) if DT_RE.search(nm)), None)
        if dt_idx is not None:
            img_idx = next((i for i in range(dt_idx - 1, -1, -1)
                            if nodes[i][0] == "ImageControl" and nodes[i][1]), None)
            if img_idx is not None:
                d.sender = nodes[img_idx][1]
                after = [nm for ct, nm in nodes[img_idx + 1:dt_idx]
                         if ct == "TextControl" and nm]
                d.sender_org = next((nm for nm in after
                                     if nm != d.sender and len(nm) <= 25), "")
            else:
                prev = [nm for ct, nm in nodes[max(0, dt_idx - 3):dt_idx]
                        if ct == "TextControl" and 0 < len(nm) <= 25]
                if prev:
                    d.sender = prev[0]
                if len(prev) > 1:
                    d.sender_org = prev[1]

        # 제목: 발신자 이름 앞에 오는 첫 긴 TextControl
        subj = ""
        limit = dt_idx if dt_idx is not None else len(nodes)
        for ct, nm in nodes[:limit]:
            if ct == "TextControl" and len(nm) > 8 and not DT_RE.search(nm) \
                    and nm != d.sender and nm != d.sender_org and nm != DETAIL_TITLE:
                subj = nm
                break
        d.subject = subj

        # 첨부파일
        d.attachments = [nm for ct, nm in nodes
                         if ct == "CheckBoxControl" and "." in nm and nm != "첨부파일"]
        return d

    # ---------- 저수준 조작 ----------
    def _renderer(self, hwnd: int) -> Optional[int]:
        found = []
        try:
            win32gui.EnumChildWindows(
                hwnd,
                lambda h, _: (found.append(h)
                              if win32gui.GetClassName(h) == RENDER_CLASS else None, True)[-1],
                None,
            )
        except Exception:
            return None
        return found[0] if found else None

    def _click(self, x: int, y: int, hwnd: Optional[int] = None,
               double: bool = False) -> bool:
        """
        화면 좌표로 실제 마우스를 움직이는 대신, 창에 마우스 메시지를 직접 보낸다.

        이렇게 하는 이유:
          · 커서가 움직이지 않아 선생님 작업을 방해하지 않는다
          · 브리티 창이 다른 창에 가려져 있어도 정확히 전달된다
            (좌표 클릭은 위에 덮인 창이 대신 받아버린다 — 실제로 발생했던 실패)
        """
        target = hwnd or self.hwnd
        rh = self._renderer(target)
        if rh is None:
            return False
        try:
            lx, ly = win32gui.ScreenToClient(rh, (int(x), int(y)))
        except Exception:
            return False
        lp = win32api.MAKELONG(lx, ly)
        seq = [(win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON),
               (win32con.WM_LBUTTONUP, 0)]
        if double:
            seq += [(win32con.WM_LBUTTONDBLCLK, win32con.MK_LBUTTON),
                    (win32con.WM_LBUTTONUP, 0)]
        for msg, wp in seq:
            try:
                win32gui.PostMessage(rh, msg, wp, lp)
            except Exception:
                return False
            time.sleep(0.05)
        return True

    def _close(self, hwnd: int) -> None:
        try:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            time.sleep(0.4)
        except Exception:
            pass

    def restore(self) -> None:
        # 우리가 되살린 창이라면 원래 있던 상태로 돌려놓는다
        if self.hwnd and getattr(self, "_was_hidden", False):
            try:
                if win32gui.IsWindowVisible(self.hwnd):
                    win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
            except Exception:
                pass
        elif self._was_iconic and self.hwnd:
            try:
                if not win32gui.IsIconic(self.hwnd):
                    win32gui.ShowWindow(self.hwnd, win32con.SW_MINIMIZE)
            except Exception:
                pass
        if self._saved_cursor:
            try:
                win32api.SetCursorPos(self._saved_cursor)
            except Exception:
                pass
            self._saved_cursor = None
