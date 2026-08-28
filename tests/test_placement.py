# -*- coding: utf-8 -*-
"""
패널이 '보이는 자리'에 뜨는지 검증.

메움은 패널이 곧 엔진이라, 패널이 화면 밖에 뜨면 선생님 눈에는
'자동 실행이 안 된 것'과 똑같다. 실제로 저장된 좌표가 x=4409 인데
화면은 0~3840 이어서 그런 일이 있었다. 그 판단을 여기서 묶어 둔다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meum.widget import clamp_to_screen   # noqa: E402

fails = []
W = 380                                   # 패널 폭
SCREEN = (0, 0, 3840, 1080)               # 화면 두 대를 붙여 쓰는 경우
ONE = (0, 0, 1920, 1080)                  # 한 대만 남은 경우
DEFAULT = (1540, 0)                       # 주 화면 오른쪽 기본 자리


def check(label, got, want):
    if got == want:
        print(f"  [OK  ] {label}")
    else:
        print(f"  [실패] {label}\n         받은 값 {got!r} / 기대 {want!r}")
        fails.append(label)


print("\n1. 화면 밖 좌표는 기본 자리로 되돌린다")

check("모니터를 빼서 화면 밖이 된 경우 (x=4409)",
      clamp_to_screen(4409, -1, W, ONE, DEFAULT), (1540, 0, True))
check("왼쪽으로 완전히 벗어난 경우",
      clamp_to_screen(-500, 0, W, ONE, DEFAULT), (1540, 0, True))
check("아래로 완전히 벗어난 경우",
      clamp_to_screen(100, 2000, W, ONE, DEFAULT), (1540, 0, True))
check("저장된 값이 없으면 기본 자리",
      clamp_to_screen(None, None, W, ONE, DEFAULT), (1540, 0, True))


print("\n2. 화면 안이면 그대로 둔다")

check("두 번째 화면에 놓아둔 경우",
      clamp_to_screen(3400, 0, W, SCREEN, DEFAULT), (3400, 0, False))
check("주 화면 왼쪽에 놓아둔 경우",
      clamp_to_screen(40, 0, W, SCREEN, DEFAULT), (40, 0, False))


print("\n3. 살짝 걸친 것은 안으로 당긴다")

# 오른쪽 끝을 넘겼지만 화면에 걸쳐 있다 → 밀어 넣는다
check("오른쪽으로 조금 넘친 경우",
      clamp_to_screen(1700, 0, W, ONE, DEFAULT), (1540, 0, True))
check("위로 조금 올라간 경우",
      clamp_to_screen(1000, -30, W, ONE, DEFAULT), (1000, 0, True))


print("\n" + "=" * 58)
if fails:
    print(f"실패 {len(fails)}건: {', '.join(fails)}")
    sys.exit(1)
print("전부 통과")
