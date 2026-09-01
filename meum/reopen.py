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

import win32api
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
    from .collector import (BrityCollector, _find_all, _find_first,
                            wake_accessibility)

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

    # 1) 이미 떠 있는 쪽지 창 가운데 있는가 — 그러면 앞으로만 가져오면 된다.
    #    브리티는 이미 열려 있는 쪽지를 누르면 새 창을 띄우지 않고 그 창을 앞으로
    #    올린다. 예전에는 그걸 모르고 '새 창' 만 기다리다 10초 뒤에
    #    '쪽지 창이 열리지 않았습니다' 로 끝났다(실측).
    for h in _brity_notes(col):
        try:
            det = col._read_detail(h)
        except Exception:
            continue
        if det and (_norm(det.subject)[:24] == want or want in _norm(det.subject)):
            _front(h)
            return True, "브리티에서 원래 쪽지를 열었습니다."

    # 창이 내려가 있으면 되살린다. 수집기 _open_once 와 같은 준비다.
    col.ensure_restored()
    col._wait_no_detail()

    before = set(_brity_notes(col))
    fg_before = win32gui.GetForegroundWindow()

    # **누르기 직전에 좌표를 다시 구한다.**
    # 목록을 훑는 사이에 목록이 밀리거나 새로 고쳐지면 그때 읽어 둔 자리는
    # 이미 다른 줄이거나 줄 사이 빈 곳이다. 그러면 아무 창도 뜨지 않고
    # 10초를 헛기다린 뒤 '쪽지 창이 열리지 않았습니다' 로 끝났다(실측).
    # 수집기가 쪽지를 열 때 같은 이유로 좌표를 다시 구한다.
    rect = col._current_rect(target) or target.rect
    l, t, r, b = rect
    if r - l <= 0:
        return False, "쪽지가 목록에서 밀려났습니다. 목록을 새로 고친 뒤 다시 눌러 주세요."
    col._click(l + (r - l) // 2, t + (b - t) // 2, double=True)

    deadline = time.time() + 10
    while time.time() < deadline:
        time.sleep(0.25)
        new = set(_brity_notes(col)) - before
        if new:
            h = next(iter(new))
            wake_accessibility(h)
            time.sleep(0.6)
            _front(h)
            return True, "브리티에서 원래 쪽지를 열었습니다."
        # 이미 열려 있던 창이 앞으로 나온 경우
        fg = win32gui.GetForegroundWindow()
        if fg != fg_before and fg in before:
            _front(fg)
            return True, "브리티에서 원래 쪽지를 열었습니다."
    return False, "쪽지 창이 열리지 않았습니다."


def _brity_notes(col) -> list:
    """
    **브리티의** 쪽지 창만 골라낸다.

    창 클래스가 Chrome_WidgetWin_1 이라 크롬 탭이나 일렉트론 앱 창까지 함께
    걸린다. 그대로 두면 기다리는 사이에 선생님이 크롬 창 하나만 새로 띄워도
    그것을 '열린 쪽지' 로 알고 엉뚱한 창을 앞으로 가져왔다.
    그래서 브리티 프로세스의 창만 남긴다.
    """
    import win32process
    from .collector import brity_pids
    pids = brity_pids()
    out = []
    for h, _t in _visible(col):
        try:
            if win32process.GetWindowThreadProcessId(h)[1] in pids:
                out.append(h)
        except Exception:
            continue
    return out


def _visible(col):
    from .collector import _visible_widget_windows
    return _visible_widget_windows()


# --------------------------------------------------------------------------
def _goe_key(body: str) -> str:
    """수집할 때와 똑같은 방식으로 본문 키를 만든다 (goe_collector.GoeNote.key)."""
    from .goe_collector import normalize
    return "goe-" + hashlib.sha1(
        _norm(normalize(body or "")).encode("utf-8")).hexdigest()


def _read_body_wait(col, hwnd: int, timeout: float = 2.0) -> str:
    """
    쪽지 본문을 **채워질 때까지 기다렸다가** 읽는다.

    창이 뜬 그 순간에 읽으면 아직 글자가 들어오기 전이라 빈 값이 나온다.
    빈 값은 어느 쪽지와도 맞지 않으므로, 예전에는 맞는 줄을 열어 놓고도
    '아니네' 하고 닫아 버렸다. 그래서 끝까지 뒤지다 못 찾았다(실측).

    비어 있으면 잠깐 기다렸다 다시 읽고, 그래도 비면 빈 값을 돌려준다.
    """
    deadline = time.time() + timeout
    while True:
        body = col._read_body(hwnd) or ""
        if body.strip():
            return body
        if time.time() >= deadline:
            return ""
        time.sleep(0.06)


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


# --------------------------------------------------------------------------
# 줄 생김새 기억하기 (쪽지함 목록은 글자로 읽을 수 없다)
#
# GOE 쪽지함은 UI Automation 도 MSAA 도 자식을 하나도 내주지 않는다(실측).
# 어느 줄이 무슨 쪽지인지 아는 길은 '열어 보는 것' 뿐이라, 맞는 줄을 찾을
# 때까지 창이 여러 번 떴다 사라졌다.
#
# 그런데 줄의 **생김새**는 화면에서 그대로 읽을 수 있다. 한 번 열어 보고
# 나면 '이 줄은 그 쪽지' 라고 지문을 남겨 둔다. 다음부터는 지문만 맞춰
# 곧바로 그 줄을 누르므로 창이 한 번만 뜬다.
#
# 실측: 같은 줄을 1초 간격으로 찍어도 지문 차이 0, 서로 다른 줄은 모두
# 구별되었다.
THUMB_KEY = "goe_thumbs"
FP_W, FP_H = 32, 8              # 지문 크기 (256칸)
FP_NEAR = 26                    # 이만큼 이내면 같은 줄로 본다


def _grab_list(col):
    """쪽지함 목록을 그림으로 뜬다. 실패하면 None."""
    try:
        from PIL import ImageGrab
        l, t, r, b = win32gui.GetWindowRect(col.list_hwnd)
        if r - l < 40 or b - t < 40:
            return None
        return ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)
    except Exception:
        return None


def _row_fp(img, row: int) -> str:
    """한 줄의 생김새를 256칸 지문으로 줄인다."""
    from .goe_collector import ROW_H
    try:
        box = (0, 30 + row * ROW_H, img.width, 30 + (row + 1) * ROW_H)
        if box[3] > img.height:
            return ""
        g = img.crop(box).convert("L").resize((FP_W, FP_H))
        px = list(g.getdata())
        avg = sum(px) / len(px)
        return "".join("1" if v > avg else "0" for v in px)
    except Exception:
        return ""


def _fp_dist(a: str, b: str) -> int:
    if not a or not b or len(a) != len(b):
        return 10 ** 6
    return sum(1 for x, y in zip(a, b) if x != y)


def _load_thumbs() -> dict:
    import json
    try:
        from .state import State
        st = State()
        try:
            raw = st.get_meta(THUMB_KEY)
            d = json.loads(raw) if raw else {}
            return d if isinstance(d, dict) else {}
        finally:
            st.close()
    except Exception:
        return {}


def _save_thumbs(d: dict) -> None:
    import json
    if not d:
        return
    try:
        from .state import State
        st = State()
        try:
            # 너무 불어나지 않게 최근 400건만 남긴다
            items = list(d.items())[-400:]
            st.set_meta(THUMB_KEY, json.dumps(dict(items)))
        finally:
            st.close()
    except Exception:
        pass


# --------------------------------------------------------------------------
# 쪽지함 검색으로 곧장 찾기 (엔터 제출)
#
# GOE 쪽지함은 목록을 글자로 읽을 수 없어(UIA·MSAA 모두 자식 0개), 줄을
# 하나하나 열어 봐야 했다. 대신 쪽지함의 검색(내용)에 본문 낱말 하나를
# 넣으면 목록이 그 쪽지로 좁혀져 **창이 한 번만 뜬다**.
#
# 어렵게 배운 것들 (전부 실측):
#  · 검색줄은 알림/수신함/발신함 층마다 있어 겹친다. 검색어 칸(넓다,
#    ~99px)에만 넣는다 — 범주 칸(~65px)에 부으면 범주가 망가진다.
#  · 검색 단추는 여섯 개가 겹쳐 있고 죽은 층 것을 누르면 화면이 엉뚱한
#    층으로 넘어간다. 단추는 아예 안 쓰고 **엔터로 제출한다**.
#  · 글자는 WM_CHAR 로 들어간다. 지우기는 백스페이스가 안 먹고
#    **Ctrl+A(WM_CHAR 1) 뒤 덮어쓰기**만 된다.
#  · 검색·비우기 뒤에는 화면이 다른 층에 갇힐 수 있다. 쪽지함 탭과
#    수신함 단추를 마우스 메시지로 눌러 **시야를 복구**해야 한다.
#  · 끝나면 반드시 검색어를 비운다. 안 그러면 선생님 쪽지함이 걸러진
#    채로 남는다.
# 전부 메시지 방식이라 진짜 마우스·키보드는 건드리지 않는다.


def _mclick(h) -> None:
    try:
        r = win32gui.GetWindowRect(h)
        lx, ly = win32gui.ScreenToClient(h, ((r[0]+r[2])//2, (r[1]+r[3])//2))
        lp = win32api.MAKELONG(lx, ly)
        win32gui.PostMessage(h, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
        win32gui.PostMessage(h, win32con.WM_LBUTTONUP, 0, lp)
        time.sleep(0.15)
    except Exception:
        pass


def _goe_search_parts(col):
    """(검색어 칸들, 시야 복구용 탭들) 을 찾는다."""
    wl, wt, wr, wb = win32gui.GetWindowRect(col.hwnd)
    kws, tabs_note, tabs_inbox = [], [], []

    def cb(h, _):
        try:
            r = win32gui.GetWindowRect(h)
            cls = win32gui.GetClassName(h)
            txt = win32gui.GetWindowText(h).strip()
        except Exception:
            return True
        if cls == "UltariChildEdit" and wt + 90 <= r[1] <= wt + 150            and r[2] - r[0] >= 80:
            kws.append(h)
        elif cls == "Button" and txt == "쪽지함":
            tabs_note.append(h)
        elif cls == "Button" and txt == "수신함":
            tabs_inbox.append(h)
        return True

    try:
        win32gui.EnumChildWindows(col.hwnd, cb, None)
    except Exception:
        pass
    return kws, tabs_note + tabs_inbox


def _goe_submit(col, kws, tabs, text: str) -> None:
    """검색어를 넣고 엔터로 제출한 뒤 시야를 수신함으로 복구한다."""
    for k in kws:
        _mclick(k)
        win32gui.PostMessage(k, win32con.WM_CHAR, 1, 0)      # Ctrl+A
        time.sleep(0.08)
        if not text:
            win32gui.PostMessage(k, win32con.WM_CHAR, 8, 0)
            time.sleep(0.1)
        for ch in text:
            win32gui.PostMessage(k, win32con.WM_CHAR, ord(ch), 0)
            time.sleep(0.03)
        win32gui.PostMessage(k, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
        win32gui.PostMessage(k, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
        win32gui.PostMessage(k, win32con.WM_CHAR, 13, 0)
        time.sleep(0.7)
    for h in tabs:
        _mclick(h)
        time.sleep(0.6)


def _pick_keyword(msg_id: str) -> str:
    """저장된 본문에서 검색어로 쓸 낱말 하나를 고른다 (구절은 안 걸린다)."""
    try:
        import re as _re
        from .goe_collector import normalize
        from .state import State
        st = State()
        try:
            row = st.con.execute(
                "SELECT subject, COALESCE(body_latest, body_raw, '') "
                "FROM messages WHERE msg_id=?", (msg_id,)).fetchone()
        finally:
            st.close()
        if not row:
            return ""
        text = (row[0] or "") + " " + normalize(row[1] or "")
        words = _re.findall(r"[가-힣A-Za-z0-9]{4,12}", text)
        common = {"선생님", "안녕하세요", "안녕하십니까", "부탁드립니다",
                  "감사합니다", "안내드립니다", "드립니다", "바랍니다",
                  "선생님들", "주시기", "합니다"}
        words = [w for w in words if w not in common]
        if not words:
            return ""
        # 흔한 낱말('김우영' 같은 이름)로 검색하면 같은 낱말을 담은 쪽지가
        # 여럿 걸려 세 줄 안에 없을 수 있다(실측). **다른 쪽지에 가장 안
        # 나오는 낱말**을 고른다 — 그 쪽지만의 낱말일수록 한 번에 맞는다.
        uniq = list(dict.fromkeys(words))[:40]
        st2 = State()
        try:
            def rarity(w):
                return st2.con.execute(
                    "SELECT COUNT(*) FROM messages WHERE source='goe' "
                    "AND msg_id != ? AND (subject LIKE ? OR body_latest LIKE ?)",
                    (msg_id, f"%{w}%", f"%{w}%")).fetchone()[0]
            scored = sorted(uniq, key=lambda w: (rarity(w), -len(w)))
        finally:
            st2.close()
        return scored[0]
    except Exception:
        return ""


def _search_goe(col, msg_id: str) -> bool:
    """검색으로 좁혀 그 쪽지를 연다. 성공하면 창을 앞에 두고 True."""
    from .goe_collector import ROW_H
    kws, tabs = _goe_search_parts(col)
    keyword = _pick_keyword(msg_id)
    if not (kws and tabs and keyword):
        return False
    found = None                       # (hwnd, 원래자리)
    try:
        _goe_submit(col, kws, tabs, keyword)
        l, t, r, b = win32gui.GetWindowRect(col.list_hwnd)
        for row in range(3):           # 좁혀졌으니 위쪽 세 줄이면 충분하다
            h, home, is_new = _peek_row(col, t + 30 + row * ROW_H, timeout=2.5)
            if h is None:
                break
            if not is_new:
                continue
            body = _read_body_wait(col, h)
            if body and _goe_key(body) == msg_id:
                found = (h, home)
                break
            col._close(h)
            time.sleep(0.2)
        return found is not None
    except Exception:
        return found is not None
    finally:
        # 걸러 둔 목록을 반드시 원래대로 (찾은 창은 화면 밖에 잠시 대기)
        try:
            _goe_submit(col, kws, tabs, "")
        except Exception:
            pass
        if found:
            _unpark(found[0], found[1])
            _front(found[0])


def _scroll_to_top(col) -> None:
    """
    쪽지함을 맨 위로 올린다.

    col.scroll() 은 한 칸마다 0.15초를 쉬어 마흔 칸이면 6초가 걸린다.
    여기서는 자리만 맞추면 되므로 촘촘히 보내고 마지막에만 한 번 쉰다
    (실측: 6.5초 → 1.2초).
    """
    try:
        l, t, r, b = win32gui.GetWindowRect(col.list_hwnd)
        cx, cy = (l + r) // 2, (t + b) // 2
        lp = win32api.MAKELONG(cx, cy)
        for _ in range(40):
            win32gui.PostMessage(col.list_hwnd, win32con.WM_MOUSEWHEEL,
                                 win32api.MAKELONG(0, 120), lp)
            time.sleep(0.02)
        time.sleep(0.45)
    except Exception:
        pass


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

    # 더블클릭하셨으면 **일단 메신저부터 눈앞에 떠야 한다** (브리티와 같게).
    # 쪽지를 찾는 일은 그 다음이다. 못 찾더라도 메신저는 이미 떠 있다.
    _front(col.hwnd)

    # 1) 이미 떠 있는 쪽지 창 가운데 있는가 — 클릭조차 필요 없다
    for h in list(_visible_notes()):
        try:
            if _goe_key(_read_body_wait(col, h)) == msg_id:
                _front(h)
                return True, "GOE메신저에서 원래 쪽지를 열었습니다."
        except Exception:
            continue

    # 2) 쪽지함 검색으로 곧장 좁혀 본다 — 창이 한 번만 뜬다.
    #    검색이 빗나가면(같은 낱말 쪽지가 많거나 지워진 쪽지) 아래의
    #    줄 훑기로 넘어가지 않고 메신저에 맡긴다 — 깜빡임을 늘리지 않는다.
    kws_chk, tabs_chk = _goe_search_parts(col)
    if kws_chk and tabs_chk and _pick_keyword(msg_id):
        if _search_goe(col, msg_id):
            return True, "GOE메신저에서 원래 쪽지를 열었습니다."
        return True, ("그 쪽지를 바로 찾지 못해 GOE메신저를 열어 드렸습니다. "
                      "쪽지함에서 확인해 주세요.")

    # 3) (검색을 쓸 수 없을 때) 목록을 맨 위로 올린 뒤 예상 줄부터 확인한다.
    #
    #    쪽지함은 선생님이 보시던 자리에 스크롤되어 있을 수 있다. 그러면
    #    '맨 위가 최신' 이라는 전제가 깨져 저장해 둔 순서(rank)가 통째로
    #    어긋나고, 맞는 줄을 영영 못 찾는다(실측: 12건 중 11건 실패).
    #    맨 위로 올려 두면 rank 가 곧 줄 번호가 되어 한 번에 맞는다.
    _scroll_to_top(col)

    l, t, r, b = win32gui.GetWindowRect(col.list_hwnd)
    n_rows = max(1, min(max_rows, ((b - 10) - (t + 30)) // ROW_H + 1))

    order = _goe_order()
    rank = order.index(msg_id) if msg_id in order else None

    # 예상 줄이 화면 밖이면 목록을 내려서 찾아간다.
    # 예전에는 '보이는 범위를 지나 있습니다. 아래로 내리신 뒤 다시 눌러 주세요'
    # 라고 떠넘겼는데, 내리는 일은 프로그램이 할 수 있는 일이다.
    # 예상 줄이 화면 안이어도 목록을 내려 본다.
    #
    # 예전에는 rank 가 화면 안(0~7)이면 pages=1 이라 **한 번도 내려보지
    # 않았다.** 그런데 저장해 둔 순서는 실제 쪽지함과 어긋나기 쉽다
    # (수집하지 못한 쪽지가 섞이거나, 선생님이 쪽지를 지우시면 밀린다).
    # 실측: 예상 줄 2번이라 8줄만 훑고 끝냈는데 그 8줄 가운데 6줄이
    # 아예 우리가 모르는 쪽지였다 — 찾을 수가 없었다.
    pages = 3
    if rank is not None and rank >= n_rows:
        pages = min(8, rank // n_rows + 3)

    # 지문으로 '그 줄' 을 바로 짚어 본다. 맞으면 창이 한 번만 뜬다.
    thumbs = _load_thumbs()
    want_fp = thumbs.get(msg_id, "")
    fp_row = None
    img = _grab_list(col)
    row_fps = {}
    if img:
        for rw in range(n_rows):
            fp = _row_fp(img, rw)
            if fp:
                row_fps[rw] = fp
        if want_fp:
            best, bd = None, 10 ** 6
            for rw, fp in row_fps.items():
                d = _fp_dist(want_fp, fp)
                if d < bd:
                    best, bd = rw, d
            if best is not None and bd <= FP_NEAR:
                fp_row = best

    scrolled = 0
    opened = None
    learned = {}            # 이번에 알아낸 {쪽지열쇠: 줄 지문}
    # 오래 뒤지지 않는다. 메신저는 이미 떠 있으므로, 이 시간 안에 못
    # 찾으면 손을 떼고 선생님께 맡긴다 (예전엔 최대 150초까지 깜빡였다).
    give_up_at = time.time() + 5.0
    try:
        for page in range(pages):
            todo = _near_first(rank if page == 0 else None, n_rows)
            if page == 0 and fp_row is not None:
                todo = [fp_row] + [x for x in todo if x != fp_row]
            tried = set()
            while todo:
                if time.time() > give_up_at:
                    todo = []
                    break
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
                body = _read_body_wait(col, h)
                if not body.strip():
                    # 본문을 끝내 못 읽었다. '아니다' 가 아니라 '모르겠다' 이므로
                    # 건너뛰기 계산에도 쓰지 않는다.
                    col._close(h)
                    opened = None
                    continue
                key = _goe_key(body)
                if page == 0 and row in row_fps:
                    learned[key] = row_fps[row]
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

            if time.time() > give_up_at:
                break
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
        # 알아낸 줄 지문을 남긴다 — 다음엔 그 줄을 바로 누른다
        if learned:
            thumbs.update(learned)
            _save_thumbs(thumbs)

        # 내려놓은 목록은 맨 위로 되돌려 둔다.
        # (원래 보시던 자리까지 정확히 되돌릴 방법이 없다. 맨 위가
        #  쪽지함의 기본 자리이므로 그 자리로 둔다)
        if scrolled:
            try:
                col.scroll(-(scrolled + 3))
            except Exception:
                pass

    # 쪽지를 못 찾아도 빈손으로 끝내지 않는다 — GOE메신저를 앞으로
    # 띄워 드린다. 더블클릭했으면 어쨌든 메신저가 눈앞에 떠야 한다.
    _front(col.hwnd)
    return True, ("그 쪽지를 바로 찾지 못해 GOE메신저를 열어 드렸습니다. "
                  "쪽지함에서 확인해 주세요.")


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
