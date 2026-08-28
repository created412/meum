# -*- coding: utf-8 -*-
"""
할 일에서 '원래 쪽지'로 되돌아가기.

패널의 항목을 두 번 누르면 그 할 일이 나온 쪽지를 메신저에서 다시 띄운다.
요약본만 보고는 판단이 안 될 때(첨부파일·앞뒤 맥락) 원문을 봐야 하기 때문이다.

브리티와 GOE 는 찾는 방법이 다르다.

  브리티 — 목록에 제목이 그대로 보이므로 글자를 맞춰 찾는다
  GOE   — 목록을 읽을 수 없으므로 위에서부터 열어 보며 본문을 맞춰 찾는다
          (수집할 때 이미 열어 본 쪽지들이라 '읽음' 상태는 그대로다)

찾은 창은 닫지 않고 그대로 둔다. 선생님이 보셔야 하니까.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Optional, Tuple

import win32con
import win32gui


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _front(hwnd: int) -> None:
    """창을 앞으로 가져온다. 실패해도 그냥 넘어간다."""
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        try:
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW)
        except Exception:
            pass


# --------------------------------------------------------------------------
def _open_brity(cfg: dict, subject: str, sender: str) -> Tuple[bool, str]:
    from .collector import BrityCollector, _find_all, _find_first

    col = BrityCollector(cfg, log=lambda s: None)
    col.attach()
    col.ensure_restored() if hasattr(col, "ensure_restored") else None
    col._ensure_note_tab()

    want = _norm(subject)[:24]
    if not want:
        return False, "찾을 제목이 없습니다."

    root = col._root()
    lst = _find_first(root, lambda x: x.ControlTypeName == "ListControl")
    if lst is None:
        return False, "브리티 쪽지 목록을 찾지 못했습니다."

    target = None
    for item in _find_all(lst, lambda x: x.ControlTypeName == "ListItemControl",
                          maxdepth=6):
        note = col._parse_list_item(item)
        if not note:
            continue
        if _norm(note.preview)[:24] == want or want in _norm(note.preview):
            target = note
            break
    if target is None:
        return False, "브리티 목록에서 그 쪽지를 찾지 못했습니다.\n(오래되어 목록에서 밀려났을 수 있습니다)"

    before = {h for h, _ in _visible(col)}
    l, t, r, b = target.rect
    col._click(l + (r - l) // 2, t + (b - t) // 2, double=True)

    deadline = time.time() + 10
    while time.time() < deadline:
        time.sleep(0.4)
        new = {h for h, _ in _visible(col)} - before
        if new:
            h = next(iter(new))
            time.sleep(0.6)
            _front(h)
            return True, "브리티에서 원래 쪽지를 열었습니다."
    return False, "쪽지 창이 열리지 않았습니다."


def _visible(col):
    from .collector import _visible_widget_windows
    return _visible_widget_windows()


# --------------------------------------------------------------------------
def _goe_key(body: str) -> str:
    """수집할 때와 똑같은 방식으로 본문 키를 만든다 (goe_collector.GoeNote.key)."""
    from .goe_collector import normalize
    return "goe-" + hashlib.sha1(
        _norm(normalize(body or "")).encode("utf-8")).hexdigest()


def _goe_order() -> list:
    """
    쪽지함 목록 순서(맨 위부터)를 짐작한다.

    가장 믿을 만한 것은 **마지막으로 훑을 때 실제로 본 줄 순서**(goe_rows)다.
    그 아래는 수집 순서로 되살린 순서를 이어 붙인다.
    """
    import json
    try:
        from .state import State
        st = State()
        try:
            seen = []
            raw = st.get_meta("goe_rows")
            if raw:
                try:
                    seen = [k for k in json.loads(raw) if isinstance(k, str)]
                except Exception:
                    seen = []
            rest = [k for k in st.goe_list_order() if k not in set(seen)]
            return seen + rest
        finally:
            st.close()
    except Exception:
        return []


def _predict_row(msg_id: str) -> Optional[int]:
    """저장해 둔 수집 순서로 '지금 몇 번째 줄'인지 계산한다."""
    order = _goe_order()
    return order.index(msg_id) if msg_id in order else None


def _near_first(predicted: Optional[int], n_rows: int) -> list:
    """
    예상 줄부터 훑을 순서. **아래쪽을 먼저 본다.**

    예상 줄은 우리가 수집해 둔 쪽지들만 세어 매긴 자리라, 아직 수집하지
    못한 쪽지가 위에 끼어 있으면 실제 위치는 예상보다 **아래**다.
    즉 예상 줄은 언제나 '적어도 이만큼은 아래' 라는 하한이다.
    위쪽은 쪽지를 지우신 경우에만 해당하므로 나중에 본다.
    """
    if predicted is None:
        return list(range(n_rows))
    down = [r for r in range(predicted, n_rows)]
    up = [r for r in range(predicted - 1, -1, -1)]
    return down + up


OFFSCREEN = (-30000, -30000)


def _park(hwnd: int) -> Optional[tuple]:
    """
    창을 화면 밖으로 치운다. 원래 자리를 돌려준다.

    감추기(SW_HIDE)로는 안 된다 — 감춘 창은 UI Automation 이 본문을
    읽어 주지 않는다(실측: 보이는 상태 180자 → 감춘 상태 0자).
    화면 밖으로 옮기면 '보이는 창'이라 본문은 그대로 읽히면서
    선생님 눈에는 띄지 않는다.
    """
    try:
        rect = win32gui.GetWindowRect(hwnd)
        win32gui.SetWindowPos(hwnd, win32con.HWND_BOTTOM,
                              OFFSCREEN[0], OFFSCREEN[1], 0, 0,
                              win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
        return rect
    except Exception:
        return None


def _unpark(hwnd: int, rect: Optional[tuple]) -> None:
    """치워 둔 창을 원래 자리로 되돌린다."""
    if not rect:
        return
    try:
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, rect[0], rect[1], 0, 0,
                              win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
    except Exception:
        pass


def _peek_row(col, y: int, timeout: float = 6.0):
    """
    한 줄을 열어 보되 **화면에는 내보내지 않는다**.

    GOE 목록은 어느 줄이 무슨 쪽지인지 읽을 수 없어서, 확인하려면 열어 보는
    수밖에 없다. 예전에는 그 확인용 창이 줄줄이 떴다 닫혀 보기 사나웠다.
    그래서 창이 뜨자마자 화면 밖으로 치우고 본문만 읽는다.

    이미 열려 있는 쪽지를 누르면 GOE 는 새 창을 띄우지 않고 그 창을 앞으로
    올린다. 그때는 기다릴 것 없이 곧바로 물러난다(예전에는 이걸 몰라서
    줄마다 6초씩 헛기다렸다 — 그래서 한참 걸렸다).

    반환: (창 핸들, 원래 자리, 새로 연 것인가)
    """
    from .goe_collector import _visible_notes

    before = _visible_notes()
    fg_before = win32gui.GetForegroundWindow()
    if not col._click_row(y):
        return None, None, False

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.03)                 # 깜빡임을 줄이려고 촘촘히 본다
        new = _visible_notes() - before
        if new:
            h = next(iter(new))
            return h, _park(h), True
        fg = win32gui.GetForegroundWindow()
        if fg != fg_before and fg in before:
            return fg, None, False       # 원래 열려 있던 창이 앞으로 나왔다
    return None, None, False


def _open_goe(cfg: dict, msg_id: str, max_rows: int = 25) -> Tuple[bool, str]:
    """
    GOE 쪽지를 곧바로 띄운다.

    GOE 목록은 직접 그리기라(UIA·MSAA 모두 자식이 없다) 어느 줄이 무슨
    쪽지인지 읽을 수 없다. 그래서 '열어서 확인'하는 길밖에 없는데,
    예전에는 그 과정이 그대로 화면에 보여 쪽지 창이 최근 것부터 차례로
    떴다 닫혔다.

    이제는 이렇게 한다.
      1. 이미 열려 있는 쪽지 창이면 클릭 없이 앞으로만 가져온다
      2. 저장해 둔 수집 순서로 '몇 번째 줄'인지 계산해 그 줄부터 확인한다
      3. 확인용으로 여는 창은 **화면에 내보내지 않는다**(_peek_row)

    그래서 선생님 눈에는 **맞는 쪽지 하나만** 뜬다.
    """
    from .goe_collector import GoeCollector, ROW_H, _visible_notes

    col = GoeCollector(cfg, log=lambda s: None)
    col.attach()

    # 1) 이미 떠 있는 쪽지 창 가운데 있는가 — 클릭조차 필요 없다
    for h in list(_visible_notes()):
        try:
            if _goe_key(col._read_body(h)) == msg_id:
                _front(h)
                return True, "GOE메신저에서 원래 쪽지를 열었습니다."
        except Exception:
            continue

    # 2) 예상 줄부터 확인한다
    l, t, r, b = win32gui.GetWindowRect(col.list_hwnd)
    n_rows = max(1, min(max_rows, ((b - 10) - (t + 30)) // ROW_H + 1))

    order = _goe_order()
    rank = order.index(msg_id) if msg_id in order else None

    # 예상 줄이 화면 밖이면 목록을 내려서 찾아간다.
    # 예전에는 '보이는 범위를 지나 있습니다. 아래로 내리신 뒤 다시 눌러 주세요'
    # 라고 떠넘겼는데, 내리는 일은 프로그램이 할 수 있는 일이다.
    pages = 1
    if rank is not None and rank >= n_rows:
        pages = min(8, rank // n_rows + 2)

    scrolled = 0
    opened = None
    try:
        for page in range(pages):
            todo = _near_first(rank if page == 0 else None, n_rows)
            tried = set()
            while todo:
                row = todo.pop(0)
                if row in tried or not (0 <= row < n_rows):
                    continue
                tried.add(row)

                h, home, is_new = _peek_row(col, t + 30 + row * ROW_H)
                if h is None:
                    continue
                if not is_new:
                    # 이미 열려 있던 쪽지다. 그런 창은 1)에서 이미 다 확인했으므로
                    # 찾는 쪽지가 아니다. 남의 창이니 닫지도, 옮기지도 않는다.
                    continue

                opened = h
                key = _goe_key(col._read_body(h))
                if key == msg_id:
                    _unpark(h, home)          # 원래 자리로 돌려놓고
                    _front(h)                 # 그때 처음으로 화면에 보인다
                    opened = None
                    return True, "GOE메신저에서 원래 쪽지를 열었습니다."

                col._close(h)
                opened = None

                # 빗나갔다면 이 줄의 정체로 '몇 칸 어긋났는지'를 알아내
                # 곧장 그 자리로 건너뛴다 (수집하지 못한 쪽지가 섞여 있을 때)
                if page == 0 and rank is not None and key in order:
                    jump = rank + (row - order.index(key))
                    if 0 <= jump < n_rows and jump not in tried:
                        todo.insert(0, jump)

            if page < pages - 1:
                col.scroll(3)
                scrolled += 3
    finally:
        # 확인하다 만 창을 화면 밖에 버려 두지 않는다
        if opened:
            try:
                col._close(opened)
            except Exception:
                pass
        # 내려놓은 목록은 선생님이 보시던 자리로 되돌린다
        if scrolled:
            try:
                col.scroll(-(scrolled + 3))
            except Exception:
                pass

    return False, ("GOE 쪽지함에서 그 쪽지를 찾지 못했습니다.\n"
                   "(지우셨거나 쪽지함에서 삭제되었을 수 있습니다)")


# --------------------------------------------------------------------------
def open_original(cfg: dict, source: str, msg_id: str,
                  subject: str = "", sender: str = "") -> Tuple[bool, str]:
    """
    할 일의 원래 쪽지를 메신저에서 띄운다.
    반환: (성공 여부, 알림 문구)
    """
    try:
        if (source or "brity") == "goe":
            return _open_goe(cfg, msg_id)
        return _open_brity(cfg, subject, sender)
    except Exception as e:
        return False, f"열지 못했습니다: {e}"
