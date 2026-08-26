# -*- coding: utf-8 -*-
"""
제목 압축과 '내 일 / 알아둘 일' 구분 검증.

전부 실제로 수집된 문장이며, 구분 판정에는 추출기가 실제로 넘겨주는
본문·유형(due_kind)·구분(category)을 그대로 준다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brity_todo.titles import shorten, classify   # noqa: E402

LEN_LIMIT = 32

# (원문, 제목에 들어가야 할 말, 기대 구분, 본문, due_kind, category)
CASES = [
    ("점검사항 확인 후 수정된 평가계획을 8/19(수) 14시까지 보내주시기 바랍니다.",
     ["평가계획", "제출"], "mine",
     "수정본은 한글파일로 제출 부탁드립니다.", "deadline", "제출"),

    ("성취도 관련하여 한 번 더 확인 부탁드립니다.",
     ["성취도", "확인"], "mine",
     "국제관계와 국제기구 교과는 성취도가 5단계라고 답변을 주셨습니다.", "none", "확인"),

    ("출결 관련하여 일출결 사유란에 최대한 명확하고 객관적인 사실이 드러나게 작성하기를 권장합니다.",
     ["작성"], "mine",
     "미인정 결석의 경우에 민원에 대한 방어를 위해서도 일출결 사유를 기재해 주세요.",
     "none", "작성"),

    ("타학교에 개설한 공동교육과정에 안화고 학생 현재까지 포기원 제출한 학생들 3명 입니다.",
     ["제출"], "mine",
     "수업교사와 개설교에 보냅니다. 업무에 참고하세요", "none", "제출"),

    ("2학년 전문가와 함께하는 과학체험교실",
     ["과학체험교실"], "notice",
     "과학중점 학생들을 대상으로 운영되는 프로그램입니다.", "event", "참석"),

    ("경기도형 탄소중립학교 심화교육",
     ["탄소중립학교"], "notice",
     "환경 키워드로 세특을 만들어가는 학생이 있다면 참여하여", "event", "참석"),

    ("2026 AI콘텐츠 청소년 창작자 과정 특강",
     ["특강"], "notice",
     "AI를 활용해 콘텐츠를 제작해보며 진로특강 및 실습을 진행합니다.", "event", "참석"),

    ('내일 화요일(8/25)은 "텀블러 데이"를 운영 합니다.',
     ["텀블러"], "notice",
     "학생들이 꼭 반드시 텀블러를 챙겨올 수 있도록 담임선생님들께서는 학급 지도와 홍보 부탁 드립니다.",
     "deadline", "안내"),
]


def main():
    fails = []
    print("원문 → 짧은 제목 [구분]")
    print("-" * 74)
    for text, must, want_kind, detail, due_kind, category in CASES:
        short = shorten(text, category)
        kind = classify(text, detail=detail, due_kind=due_kind, category=category)
        ok = all(m in short for m in must) and kind == want_kind
        if len(short) > LEN_LIMIT:
            ok = False
        print(f"  [{'OK  ' if ok else 'FAIL'}] {text[:40]}")
        print(f"          → {short!r}  [{kind}]  ({len(short)}자)")
        if not ok:
            miss = [m for m in must if m not in short]
            fails.append(f"{text[:26]}… → {short!r}[{kind}] "
                         f"빠진말={miss} 기대구분={want_kind}")

    print("\n" + "=" * 60)
    if fails:
        print(f"실패 {len(fails)}건")
        for f in fails:
            print("  · " + f)
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
