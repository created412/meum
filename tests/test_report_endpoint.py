# -*- coding: utf-8 -*-
"""
구글 폼 주소만으로 '보낼 준비'가 되는지 검증.

폼에 글을 넣으려면 entry 번호가 필요한데, 그걸 선생님께 찾으라고 하면
페이지 소스를 눈으로 뒤져야 한다. 대신 폼 페이지에서 직접 찾아낸다.
그 찾아내는 규칙이 폼 모양에 따라 깨지지 않는지 여기서 묶어 둔다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meum.doctor import _find_entry_id, send_report   # noqa: E402

fails = []


def check(label, got, want):
    if got == want:
        print(f"  [OK  ] {label}")
    else:
        print(f"  [실패] {label}\n         받은 값 {got!r} / 기대 {want!r}")
        fails.append(label)


print("\n1. 폼 페이지에서 입력 칸 번호 찾기")

check("name 속성에 있는 경우",
      _find_entry_id('<textarea name="entry.1234567890" aria-label="내용">'),
      "entry.1234567890")

check("따옴표 안에만 있는 경우",
      _find_entry_id('{"submitId":"x","fields":["entry.987654321"]}'),
      "entry.987654321")

check("FB_PUBLIC_LOAD_DATA_ 만 있는 요즘 폼",
      _find_entry_id(
          'var FB_PUBLIC_LOAD_DATA_ = [null,[null,[[123,"진단 보고서",null,1,'
          '[[555123456,null,1]]]]]];</script>'),
      "entry.555123456")

check("아무것도 없으면 None", _find_entry_id("<html><body>빈 폼</body></html>"), None)


print("\n2. 받을 주소가 없으면 보내지 않는다")
check("빈 주소", send_report("시험", ""), (False, ""))
check("공백뿐인 주소", send_report("시험", "   "), (False, ""))


print("\n" + "=" * 58)
if fails:
    print(f"실패 {len(fails)}건: {', '.join(fails)}")
    sys.exit(1)
print("전부 통과")
