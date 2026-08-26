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
def _open_goe(cfg: dict, msg_id: str, max_rows: int = 25) -> Tuple[bool, str]:
    """저장해 둔 본문 해시(msg_id)와 같은 쪽지를 찾을 때까지 열어 본다."""
    from .goe_collector import GoeCollector, normalize, _visible_notes

    col = GoeCollector(cfg, log=lambda s: None)
    col.attach()
    lst = col.list_hwnd
    l, t, r, b = win32gui.GetWindowRect(lst)

    for row in range(max_rows):
        y = t + 30 + row * 66
        if y > b - 10:
            break
        before = _visible_notes()
        if not col._click_row(y):
            continue
        opened = None
        deadline = time.time() + 6
        while time.time() < deadline:
            time.sleep(0.35)
            new = _visible_notes() - before
            if new:
                opened = next(iter(new))
                break
        if not opened:
            continue

        time.sleep(0.8)
        body = normalize(col._read_body(opened) or "")
        key = "goe-" + hashlib.sha1(_norm(body).encode("utf-8")).hexdigest()
        if key == msg_id:
            _front(opened)
            return True, "GOE메신저에서 원래 쪽지를 열었습니다."
        col._close(opened)
        for _ in range(8):
            time.sleep(0.15)
            if opened not in _visible_notes():
                break

    return False, "GOE 쪽지함에서 그 쪽지를 찾지 못했습니다.\n(오래되어 목록에서 밀려났을 수 있습니다)"


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
