# -*- coding: utf-8 -*-
"""한 쪽지에 여러 일정이 나열된 경우 검증 (실제 수집된 김도현 쪽지)."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meum import config                    # noqa: E402
from meum.extractor import RuleExtractor   # noqa: E402

cfg = dict(config.DEFAULTS)
ex = RuleExtractor(cfg)

RECV = datetime(2026, 8, 19, 13, 46)

BODY = """2학년 담임선생님들, 안녕하세요~
수리과학부에서 8, 9월에 예정된 행사 안내 드립니다.
담임선생님께서도 한 번 읽어보시고 행사에 흥미와 적성을 가진 학생이 있다면 적극 지원하도록 홍보 및 권유 부탁드리겠습니다.
포스터는 출석부함에 넣어두겠으며, 각 학급별 단톡에도 게시해주시면 대단히 감사하겠습니다.
#8/22(토) 2학년 전문가와 함께하는 과학체험교실
- 포스터 참고 - 목요일에 포스터 배부 예정
- 과학중점 학생들을 대상으로 운영되는 프로그램입니다.
- 다만, 과중 학생 수를 고려해 빈 자리에 대하여 8/20(목)에 비과중 학생들 중에서 희망자를 모으고자 미리 말씀드리오니 참고 부탁드립니다.
#8/26(수), 9/16(수) 16:00 경기도형 탄소중립학교 심화교육
- 포스터 참고
#8/28(금) 16:00 과학명사특강
- 포스터 참고
#9/14(월) 16:00 2026 AI콘텐츠 청소년 창작자 과정 특강
- 포스터 참고
#9/16(수) 16:00 2학년 수학올림픽
- 수학과 주관으로 학년 내 학급별 수학 올림픽을 강당에서 진행합니다."""

EXPECT = {
    "2026-08-22": "2학년 전문가와 함께하는 과학체험교실",
    "2026-08-26T16:00": "경기도형 탄소중립학교 심화교육",
    "2026-09-16T16:00": None,          # 두 줄에서 나오므로 제목은 검사하지 않음
    "2026-08-28T16:00": "과학명사특강",
    "2026-09-14T16:00": "2026 AI콘텐츠 청소년 창작자 과정 특강",
}


def main():
    tasks = ex.extract(subject="수리과학부 8,9월 예정 행사 안내", body=BODY,
                       sender="김도현", sender_org="", received_at=RECV)
    print(f"추출 {len(tasks)}건\n")
    got = {}
    for t in tasks:
        print(f"  {t.due_at:<20} [{t.due_kind:<8}] {t.title}")
        got.setdefault(t.due_at, t.title)

    fails = []
    if len(tasks) < 5:
        fails.append(f"일정이 5건 이상이어야 하는데 {len(tasks)}건")

    for due, title in EXPECT.items():
        if due not in got:
            fails.append(f"{due} 일정이 없음")
        elif title and title not in got[due]:
            fails.append(f"{due} 제목이 '{got[due]}' (기대: '{title}' 포함)")

    # 본문 중간 '- 다만, … 8/20(목)에 …' 은 일정이 아니다
    for t in tasks:
        if t.due_at and t.due_at.startswith("2026-08-20"):
            fails.append("본문 설명 속 8/20 을 일정으로 잘못 등록")
        if t.title.startswith(("-", "다만")):
            fails.append(f"제목이 문장 조각임: {t.title[:40]}")
        # 시각이 다른 줄에서 새어 들어오면 안 된다
        if t.due_at and t.due_at.startswith("2026-08-22") and "16:00" in t.due_at:
            fails.append("8/22 에 다른 줄의 16:00 이 딸려옴")

    print()
    if fails:
        print(f"실패 {len(fails)}건")
        for f in fails:
            print(f"  · {f}")
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
