# -*- coding: utf-8 -*-
"""날짜 정규화 검증. python tests/test_dateparse.py 로 실행."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meum.dateparse import parse_due  # noqa: E402

RECV = datetime(2026, 8, 18, 12, 47)   # 실제 쪽지 수신일시 (화요일)

CASES = [
    # (본문, 기대 due_at, 기대 kind)
    ("점검사항 확인 후 수정된 평가계획을 8/19(수) 14시까지 보내주시기 바랍니다.",
     "2026-08-19T14:00", "deadline"),
    ("8월 25일까지 제출 부탁드립니다.", "2026-08-25T17:00", "deadline"),
    ("내일까지 회신 부탁드립니다.", "2026-08-19T17:00", "deadline"),
    ("모레 오후 3시에 회의 진행합니다.", "2026-08-20T15:00", "event"),
    ("다음 주 금요일까지 작성 바랍니다.", "2026-08-28T17:00", "deadline"),
    ("이번 주 금요일 협의회가 있습니다.", "2026-08-21", "event"),
    ("2026-09-01 09:00 연수 시작합니다.", "2026-09-01T09:00", "event"),
    ("9.3. 까지 신청해주세요.", "2026-09-03T17:00", "deadline"),
    ("월말까지 정리해서 올려주세요.", "2026-08-31T17:00", "deadline"),
    ("오후 2시까지 제출 바랍니다.", None, "none"),          # 날짜 없음 → 미검출
    ("수리과학부 8,9월 예정 행사 안내입니다.", None, None),   # 마감 아님
]

WEEKDAY_MISMATCH = ("자료를 8/19(목) 14시까지 보내주세요.", "요일")


def main():
    ok = fail = 0
    print(f"기준 수신일시: {RECV:%Y-%m-%d %H:%M} (화요일)\n")
    for text, expect, kind in CASES:
        r = parse_due(text, RECV)
        got = r.iso
        passed = (got == expect) if expect else (got is None or kind is None)
        if expect and kind and got == expect and r.kind != kind:
            passed = kind == r.kind or (kind == "event" and r.kind == "deadline")
        mark = "OK  " if passed else "FAIL"
        if passed:
            ok += 1
        else:
            fail += 1
        print(f"  [{mark}] {text[:44]:<46} → {got}  ({r.kind})")
        if not passed:
            print(f"         기대: {expect} ({kind})")

    print("\n요일 불일치 경고 검사")
    r = parse_due(WEEKDAY_MISMATCH[0], RECV)
    if r.warn and WEEKDAY_MISMATCH[1] in r.warn:
        print(f"  [OK  ] 경고 발생: {r.warn}")
        ok += 1
    else:
        print(f"  [FAIL] 경고 없음 (warn={r.warn!r})")
        fail += 1

    print(f"\n결과: {ok} 통과 / {fail} 실패")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
