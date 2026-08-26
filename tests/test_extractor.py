# -*- coding: utf-8 -*-
"""실제 쪽지 본문으로 추출 엔진 검증."""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brity_todo import config                        # noqa: E402
from brity_todo.extractor import RuleExtractor, strip_quotes, normalize_thread_key  # noqa: E402

cfg = dict(config.DEFAULTS)
ex = RuleExtractor(cfg)

# --- 실제 수집된 쪽지 (2026-08-18 12:47, 김하늘/○○고등학교) ---
REAL_BODY = """안녕하세요. ○○고등학교 연구부 김하늘입니다.
제출해주신 평가계획 점검사항 보내드립니다. 점검사항 확인 후 수정된 평가계획을
8/19(수) 14시까지 보내주시기 바랍니다.(교육지원청 점검이 20일이여서 일정이 빠듯한 점 양해 부탁드립니다.)
수정본은 한글파일로 제출 부탁드립니다.
점검사항에 대해 문의사항이 있으시다면 메신저나 031-000-0000로 연락 부탁드립니다. 감사합니다."""

# --- 인용부가 붙은 스레드 (RE(2) 형태) ---
THREAD_BODY = """선생님 저희학교 교육과정부장님께 문의해보니 국제관계와 국제기구 교과는 성취도가 5단계라고 답변을 주셨습니다.

성취도 관련하여 한 번 더 확인 부탁드립니다.

---------- Original Message ----------
Sender : 홍길동 <teacher@example.kr> 2학년부/△△고등학교
Date : 2026-08-20 10:41 (GMT+9)
Title : RE: 안녕하세요. ○○고등학교 연구부 김하늘입니다.

수정 완료했습니다
---------- Original Message ----------
Date : 2026-08-18 12:47
점검사항 확인 후 수정된 평가계획을 8/19(수) 14시까지 보내주시기 바랍니다."""

# --- 단순 안내 (할 일 아님) ---
NOTICE_BODY = "방학 중 학교 유무선 네트워크 정보통신 공사 안내드립니다. 참고하시기 바랍니다."


def show(label, tasks):
    print(f"\n── {label}")
    if not tasks:
        print("   (추출 없음)")
        return
    for t in tasks:
        print(f"   제목   : {t.title}")
        print(f"   마감   : {t.due_at}  ({t.due_kind})")
        print(f"   구분   : {t.category}   확신도: {t.confidence}")
        print(f"   요청자 : {t.requester}")
        if t.evidence:
            print(f"   근거   : {t.evidence!r}")
        if t.warn:
            print(f"   경고   : {t.warn}")


def main():
    fails = []

    # 1) 실제 쪽지
    tasks = ex.extract(subject="안녕하세요. ○○고등학교 연구부 김하늘입니다.",
                       body=REAL_BODY, sender="김하늘", sender_org="○○고등학교",
                       received_at=datetime(2026, 8, 18, 12, 47))
    show("실제 쪽지 (08-18 김하늘)", tasks)
    if not tasks or tasks[0].due_at != "2026-08-19T14:00":
        fails.append("실제 쪽지의 마감이 2026-08-19T14:00 이어야 함")
    if tasks and tasks[0].category != "확인":
        pass  # 제출/확인 중 무엇이든 허용

    # 2) 인용부 제거
    latest = strip_quotes(THREAD_BODY)
    print(f"\n── 인용부 제거 결과 ({len(THREAD_BODY)}자 → {len(latest)}자)")
    print("   " + latest.replace("\n", " ")[:90])
    if "Original Message" in latest or "수정 완료했습니다" in latest:
        fails.append("인용부가 제거되지 않음")
    if "성취도 관련하여" not in latest:
        fails.append("최신 발화가 유실됨")

    tasks2 = ex.extract(subject="RE(2): 안녕하세요. ○○고등학교 연구부 김하늘입니다.",
                        body=THREAD_BODY, sender="김하늘", sender_org="○○고등학교",
                        received_at=datetime(2026, 8, 20, 13, 15))
    show("스레드 쪽지 (08-20, 인용부 포함)", tasks2)
    if tasks2 and tasks2[0].due_at and tasks2[0].due_at.startswith("2026-08-19"):
        fails.append("인용문 속 과거 마감(8/19)을 새 할 일로 잘못 인식")

    # 3) 스레드 키 동일성
    k1 = normalize_thread_key("안녕하세요. ○○고등학교 연구부 김하늘입니다.", "김하늘")
    k2 = normalize_thread_key("RE(2): 안녕하세요. ○○고등학교 연구부 김하늘입니다.", "김하늘")
    print(f"\n── 스레드 키\n   원본 : {k1}\n   RE(2): {k2}")
    if k1 != k2:
        fails.append("RE(2) 접두어 제거 후 같은 스레드로 묶이지 않음")

    # 4) 단순 안내는 걸러야 함
    tasks3 = ex.extract(subject="방학 중 학교 유무선 네트워크 정보통신 공사 안내",
                        body=NOTICE_BODY, sender="조근영", sender_org="",
                        received_at=datetime(2026, 7, 15, 9, 0))
    show("단순 안내 (공사 안내)", tasks3)
    if tasks3 and float(tasks3[0].confidence) >= 0.6:
        fails.append("단순 안내가 높은 확신도로 추출됨(오탐)")

    # 5) 마스킹
    from brity_todo.extractor import mask_sensitive
    masked = mask_sensitive(REAL_BODY)
    print(f"\n── 전화번호 마스킹: {'성공' if '031-000-0000' not in masked else '실패'}")
    if "031-000-0000" in masked:
        fails.append("전화번호가 마스킹되지 않음")

    print("\n" + "=" * 58)
    if fails:
        print(f"실패 {len(fails)}건")
        for f in fails:
            print(f"  · {f}")
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
