# -*- coding: utf-8 -*-
"""
상주 감시의 판단 논리 검증.

실제 창을 띄우지 않고, 창 목록 스냅샷과 '지금 조용한가'만 갈아 끼워
언제 정리하고 언제 참는지를 확인한다. 여기서 잘못 판단하면
근무 중에 화면이 튀거나(방해), 쪽지를 계속 놓친다(무용지물).
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meum import watcher as W   # noqa: E402

CFG = {
    "watch_enabled": True,
    "watch_poll_sec": 20,
    "watch_idle_sec": 45,
    "watch_idle_gap_min": 20,
    "watch_max_gap_min": 120,
}

BRITY, GOE = 1001, 2001


def snap(brity=True, goe=True, goe_notes=(), popups=()):
    return {"brity": BRITY if brity else None,
            "brity_pid": 777 if brity else 0,
            "goe": GOE if goe else None,
            "goe_notes": set(goe_notes),
            "brity_popups": set(popups)}


def make(**over):
    cfg = dict(CFG)
    cfg.update(over)
    return W.Watcher(cfg)


fails = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else '실패'}] {label}\n"
          f"         받은 값 {got!r} / 기대 {want!r}" if not ok
          else f"  [OK  ] {label}")
    if not ok:
        fails.append(label)


def truthy(label, got, want: bool):
    check(label, bool(got), want)


# ---------------------------------------------------------------------------
print("\n1. 신호 판단 — 언제 '정리할 일이 생겼다'고 보는가")

w = make()
first = w._signal(snap())                       # 첫 바퀴
truthy("첫 점검에서는 한 번 확인한다", first, True)

w = make()
w._signal(snap())                                # 기준선 잡기
w._last_run = datetime.now()                     # 방금 정리한 것으로 둔다
truthy("아무 변화가 없으면 가만히 있는다", w._signal(snap()), False)

w = make()
w._signal(snap())
w._last_run = datetime.now()
check("GOE 쪽지 창이 새로 뜨면 정리한다",
      w._signal(snap(goe_notes=[3001])), "GOE 쪽지가 새로 왔습니다")

w = make()
w._signal(snap(goe_notes=[3001]))                # 이미 떠 있던 창은 새 쪽지가 아니다
w._last_run = datetime.now()
truthy("원래 떠 있던 쪽지 창은 새 쪽지로 보지 않는다",
       w._signal(snap(goe_notes=[3001])), False)

w = make()
w._signal(snap(brity=False))
w._last_run = datetime.now()
check("브리티가 켜지면 정리한다", w._signal(snap()), "브리티가 켜졌습니다")

w = make()
w._signal(snap())
w._last_run = datetime.now()
check("브리티 알림 창이 뜨면 정리한다",
      w._signal(snap(popups=[4001])), "브리티 알림이 떴습니다")

w = make()
w._signal(snap(brity=False, goe=False))
truthy("메신저가 다 꺼져 있으면 아무것도 하지 않는다",
       w._signal(snap(brity=False, goe=False)), False)

w = make()
w._signal(snap())
w._last_run = datetime.now() - timedelta(minutes=25)
check("조용한 채 확인 간격이 지나면 한 번 확인한다",
      w._signal(snap()), "정기 확인")

w = make()
w._signal(snap())
w._last_run = datetime.now() - timedelta(minutes=5)
truthy("확인 간격 전이면 그냥 둔다", w._signal(snap()), False)


# ---------------------------------------------------------------------------
print("\n2. 방해 판단 — 지금 건드려도 되는가")

orig = (W.idle_seconds, W.presentation_mode, W.workstation_locked,
        W.foreground_is_messenger)


def fake(idle=999, presenting=False, locked=False, fg_messenger=False):
    W.idle_seconds = lambda: idle
    W.presentation_mode = lambda: presenting
    W.workstation_locked = lambda: locked
    W.foreground_is_messenger = lambda s: fg_messenger


try:
    w = make()
    fake(idle=120)
    truthy("자리를 비우면 정리한다", w._quiet_enough(snap(), "x")[0], True)

    fake(idle=3)
    truthy("타자를 치고 계시면 참는다", w._quiet_enough(snap(), "x")[0], False)

    fake(idle=999, presenting=True)
    truthy("수업(발표) 중이면 참는다", w._quiet_enough(snap(), "x")[0], False)

    fake(idle=999, locked=True)
    truthy("잠금 화면이면 참는다", w._quiet_enough(snap(), "x")[0], False)

    fake(idle=999, fg_messenger=True)
    truthy("메신저를 쓰고 계시면 참는다", w._quiet_enough(snap(), "x")[0], False)

    fake(idle=999)
    truthy("메신저가 꺼져 있으면 하지 않는다",
           w._quiet_enough(snap(brity=False, goe=False), "x")[0], False)

    # 너무 오래 밀렸을 때는 자리에 계셔도 한 번은 처리한다
    w = make()
    w._last_run = datetime.now() - timedelta(minutes=200)
    fake(idle=3)
    truthy("두 시간 넘게 밀리면 사용 중이어도 한 번은 정리한다",
           w._quiet_enough(snap(), "x")[0], True)

    # 단, 그 경우에도 수업 중이면 절대 건드리지 않는다
    w = make()
    w._last_run = datetime.now() - timedelta(minutes=200)
    fake(idle=3, presenting=True)
    truthy("아무리 밀려도 수업 중에는 건드리지 않는다",
           w._quiet_enough(snap(), "x")[0], False)
finally:
    (W.idle_seconds, W.presentation_mode, W.workstation_locked,
     W.foreground_is_messenger) = orig


# ---------------------------------------------------------------------------
print("\n3. 실패 후퇴 — 헛돌지 않는가")

w = make()
for expect in (5, 15, 30, 60, 60):
    w._back_off("시험")
    left = (w._quiet_until - __import__("time").monotonic()) / 60
    check(f"{w._fails}번째 실패 뒤 {expect}분 쉼", round(left), expect)


# ---------------------------------------------------------------------------
print("\n" + "=" * 58)
if fails:
    print(f"실패 {len(fails)}건: {', '.join(fails)}")
    sys.exit(1)
print("전부 통과")
