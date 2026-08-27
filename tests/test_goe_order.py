# -*- coding: utf-8 -*-
"""
GOE 쪽지를 '바로 그 줄'로 다시 띄우기 위한 순서 계산 검증.

GOE 쪽지함 목록은 직접 그리기라 UIA·MSAA 어느 쪽으로도 읽히지 않는다
(실측: 목록 창의 접근성 자식 0개). 그래서 어느 줄이 무슨 쪽지인지는
'우리가 훑을 때 본 것'으로만 알 수 있다. 여기가 틀리면 다시 띄우기가
엉뚱한 쪽지를 열게 되므로 시험으로 묶어 둔다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meum.reopen import _near_first        # noqa: E402
from meum.state import State               # noqa: E402

fails = []


def check(label, got, want):
    if got == want:
        print(f"  [OK  ] {label}")
    else:
        print(f"  [실패] {label}\n         받은 값 {got!r}\n         기대   {want!r}")
        fails.append(label)


# ---------------------------------------------------------------------------
print("\n1. 훑을 순서 — 예상 줄에서 아래쪽을 먼저 본다")

# 예상 줄은 '수집해 둔 쪽지만 세어 매긴 자리'라, 아직 수집하지 못한 쪽지가
# 위에 끼어 있으면 실제 위치는 예상보다 아래다. 그래서 아래쪽이 먼저다.
check("예상 2 · 8줄", _near_first(2, 8), [2, 3, 4, 5, 6, 7, 1, 0])
check("예상 0 · 4줄", _near_first(0, 4), [0, 1, 2, 3])
check("예상 3 · 4줄(맨 아래)", _near_first(3, 4), [3, 2, 1, 0])
check("예상 없음 · 5줄", _near_first(None, 5), [0, 1, 2, 3, 4])


# ---------------------------------------------------------------------------
print("\n2. 수집 순서로 목록 순서 되살리기")

# 한 번의 수집은 목록 맨 위에서 아래로 훑으므로 '저장 순서 = 목록 순서'이고,
# 새 쪽지는 위에 쌓이므로 '나중 회차가 위'다.
import sqlite3                                    # noqa: E402
from datetime import datetime, timedelta          # noqa: E402


class FakeState:
    """State.goe_list_order 만 떼어내 시험한다 (실제 DB 를 건드리지 않는다)."""

    def __init__(self, rows):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute("CREATE TABLE messages (msg_id TEXT, source TEXT, "
                         "processed_at TEXT)")
        for msg_id, processed in rows:
            self.con.execute("INSERT INTO messages VALUES (?,'goe',?)",
                             (msg_id, processed))

    goe_list_order = State.goe_list_order


base = datetime(2026, 8, 26, 13, 0, 0)


def at(minutes, seconds=0):
    return (base + timedelta(minutes=minutes, seconds=seconds)).isoformat()


# 1회차(13:00)에 A,B,C 를 위에서부터 수집 → 그때 목록은 A,B,C
# 2회차(16:00)에 D,E 가 새로 와서 위에 쌓임 → 지금 목록은 D,E,A,B,C
fake = FakeState([
    ("A", at(0, 1)), ("B", at(0, 2)), ("C", at(0, 3)),
    ("D", at(180, 1)), ("E", at(180, 2)),
])
check("나중 회차가 위로 온다", fake.goe_list_order(), ["D", "E", "A", "B", "C"])

# 저장에 몇 초 걸려도 같은 회차로 묶어야 한다 (2분 이내)
fake = FakeState([("A", at(0, 0)), ("B", at(0, 40)), ("C", at(1, 30))])
check("한 회차 안의 몇 초 차이는 묶는다", fake.goe_list_order(), ["A", "B", "C"])

# 회차가 셋이면 역순으로 이어 붙는다
fake = FakeState([("A", at(0)), ("B", at(60)), ("C", at(120))])
check("회차 셋은 역순으로", fake.goe_list_order(), ["C", "B", "A"])

fake = FakeState([])
check("쪽지가 없으면 빈 목록", fake.goe_list_order(), [])


# ---------------------------------------------------------------------------
print("\n" + "=" * 58)
if fails:
    print(f"실패 {len(fails)}건: {', '.join(fails)}")
    sys.exit(1)
print("전부 통과")
