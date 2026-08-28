# -*- coding: utf-8 -*-
"""
'-' 로 시작하는 줄에 적힌 마감을 놓치지 않는지 검증.

공문 쪽지에서 '-' 는 윗줄의 부연 설명이기도 하지만, **정작 지시사항을
적는 자리**이기도 하다. 예전에는 '-' 로 시작하면 줄째로 버려서, 거기 적힌
마감이 하나도 잡히지 않았다. 우연히 놓친 것이 아니라 늘 놓치고 있었다.

아래 본문은 2026-08-21 에 실제로 온 쪽지다(이름은 그대로 두되 개인정보는
없다). 이 마감을 놓치면 담임 업무가 그대로 펑크 나므로 시험으로 묶어 둔다.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meum import config, extractor as E   # noqa: E402

RECEIVED = datetime(2026, 8, 21, 15, 0)

REAL = """선생님 안녕하세요~ 학생안전부 강주은입니다.

1. [제출] 2학기 학급 자치회 조직도
다음주 금요일(8/28) 6교시는 2학기 학급회 조직시간입니다.
-첨부파일의 학급자치회 조직도를 작성하셔서 학년별로 모아 ★다다음주 월요일(8/31) 17시까지 회신★부탁드립니다.
-학급자치회는 학생생활규정에 따라 학급자치회장 1인, 부회장 1인, 서기 1인으로 구성합니다.

2. [안내] 임명장 수여식 및 대의원회
9월 4일(금) 13시 20분부터 시청각실에서 임명장 수여식이 있을 예정입니다.
"""

# 부연 설명뿐인 '-' 줄은 일정으로 만들지 않아야 한다
DETAIL_ONLY = """#8/28(금) 16:00 과학명사특강
- 장소: 시청각실
- 대상: 2학년 전체
#9/16(수) 14:00 2학년 수학올림픽
"""

fails = []


def check(label, ok, note=""):
    print(f"  [{'OK  ' if ok else '실패'}] {label}" + (f"  {note}" if note else ""))
    if not ok:
        fails.append(label)


def run(body):
    ex = E.build(config.DEFAULTS)
    return ex.extract(subject="", body=body, sender="강주은", sender_org="학생안전부",
                      received_at=RECEIVED)


print("\n1. '-' 줄에 적힌 마감을 잡는다")
tasks = run(REAL)
due = {t.due_at for t in tasks if t.due_at}
print(f"     뽑힌 마감: {sorted(due)}")

check("8/31 17시 회신 마감을 잡는다",
      any(d.startswith("2026-08-31T17:00") for d in due))
check("그 항목을 '제출'로 본다",
      any(t.category == "제출" and (t.due_at or "").startswith("2026-08-31")
          for t in tasks))
check("제목에 '조직도' 가 남는다",
      any("조직도" in (t.short_title or t.title)
          for t in tasks if (t.due_at or "").startswith("2026-08-31")))
check("8/28 학급회 시간도 함께 잡는다",
      any(d.startswith("2026-08-28") for d in due))
check("9/4 임명장 수여식도 함께 잡는다",
      any(d.startswith("2026-09-04") for d in due))


print("\n2. 설명뿐인 '-' 줄은 일정으로 만들지 않는다")
tasks2 = run(DETAIL_ONLY)
titles = [(t.short_title or t.title) for t in tasks2]
print(f"     뽑힌 제목: {titles}")
check("장소·대상 줄은 일정이 되지 않는다",
      not any("시청각실" in t or "2학년 전체" in t for t in titles))
check("행사 두 건은 그대로 잡는다", len(tasks2) >= 2, f"{len(tasks2)}건")


print("\n" + "=" * 58)
if fails:
    print(f"실패 {len(fails)}건: {', '.join(fails)}")
    sys.exit(1)
print("전부 통과")
