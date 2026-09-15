# -*- coding: utf-8 -*-
"""
전달 쪽지 · 수집 멈춤 규칙 회귀 시험.

  1. 본문 전체가 '---- 원본메시지 ----' 안에 든 전달 쪽지도 본문이 살아
     있고, 그 안의 마감이 뽑힌다 (예전엔 빈 본문으로 버려졌다)
  2. 일반 답장은 예전대로 인용 앞의 최신 발화만 남긴다
  3. 제목이 구분선·발신자 줄로 잡히지 않는다
  4. GOE 수집은 아는 쪽지 두 개로 멈추지 않는다 (가짜 목록으로 흉내)
  5. 전달 쪽지의 옛 발신시간 때문에 멈추지 않는다
  6. 두 달 넘은 쪽지는 새로 들이지 않는다

모든 이름·내용은 지어낸 것이다.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from meum import config                                   # noqa: E402
from meum.extractor import RuleExtractor, strip_quotes    # noqa: E402
from meum import goe_collector as G                       # noqa: E402

NL = chr(10)
FAILS = []


def check(label, cond):
    print(f"  [{'OK  ' if cond else 'FAIL'}] {label}")
    if not cond:
        FAILS.append(label)


FORWARDED = NL.join([
    "-------------------- 원본메시지 --------------------",
    "발 신 자 : 김하늘 교사(중등)",
    "발신시간 : 2026-09-08 오후 04:27",
    "",
    "2학년 담임선생님들, 안녕하세요",
    "수리과학부에서 다음 주 수요일(9/16) 진행되는 수학올림픽 안내드립니다.",
    "각 학급에서는 8명을 1개 팀으로 편성하여 9/11(금)까지 명단 제출 부탁드립니다.",
])

REPLY = NL.join([
    "확인했습니다. 수정본 다시 올리겠습니다.",
    "",
    "-------------------- 원본메시지 --------------------",
    "발 신 자 : 이서연 교사",
    "발신시간 : 2026-09-01 오전 11:08",
    "수정본을 9/3(목)까지 제출 부탁드립니다.",
])


def part_extract():
    print("1~3. 전달 쪽지 본문·제목")
    body = strip_quotes(FORWARDED)
    check("전달 쪽지 본문이 비지 않는다", len(body) > 20)
    check("구분선·발신자 줄은 본문에서 빠진다",
          "원본메시지" not in body and "발 신 자" not in body)
    check("일반 답장은 인용 앞만 남긴다",
          strip_quotes(REPLY) == "확인했습니다. 수정본 다시 올리겠습니다.")

    subj = G.guess_subject(FORWARDED)
    check("제목이 구분선이 아니다", not subj.startswith("---"))
    check("제목이 발신자 줄이 아니다", "발 신 자" not in subj)

    ex = RuleExtractor(dict(config.DEFAULTS))
    tasks = ex.extract(subject=subj, body=FORWARDED, sender="김하늘 교사",
                       sender_org="", received_at=datetime(2026, 9, 8, 16, 27))
    dues = {t.due_at[:10] for t in tasks if t.due_at}
    check("전달 쪽지에서 할 일이 뽑힌다", len(tasks) >= 1)
    check("그 마감(9/11 또는 9/16)이 잡힌다",
          bool(dues & {"2026-09-11", "2026-09-16"}))


# --------------------------------------------------------------------------
class FakeCollector(G.GoeCollector):
    """화면 없이 목록 순서만 흉내 낸다. rows: 위에서부터의 본문들."""

    def __init__(self, rows):
        super().__init__({}, log=lambda s: self.logs.append(s))
        self.logs = []
        self._rows = rows
        self._i = 0
        self.list_hwnd = 1

    def row_metrics(self):
        return (0, 10, 8, 100, 100)

    def _open_row(self, y):
        if self._i >= len(self._rows):
            return None
        b = self._rows[self._i]
        self._i += 1
        return b

    def scroll(self, notches):
        pass


def _note(text, when=None):
    if when is None:
        return text
    return NL.join(["-------------------- 원본메시지 --------------------",
                    "발 신 자 : 가상 교사",
                    f"발신시간 : {when:%Y-%m-%d} 오전 10:00", "", text])


def _run(rows, known, **kw):
    import win32gui
    orig_rect, orig_vis = win32gui.GetWindowRect, G._visible_notes
    win32gui.GetWindowRect = lambda h: (0, 0, 100, 100)
    G._visible_notes = lambda: []
    try:
        fc = FakeCollector(rows)
        keys = {G.GoeNote(body=G.normalize(b), collected_at=datetime.now()).key
                for b in known}
        notes = fc.collect(known_keys=keys, max_rows=len(rows) + 2, **kw)
        return [n.body for n in notes], fc.logs
    finally:
        win32gui.GetWindowRect, G._visible_notes = orig_rect, orig_vis


def part_stop():
    print(NL + "4~6. GOE 수집 멈춤 규칙")
    now = datetime.now()

    # 4. 아는 쪽지 두 개 아래에 숨은 새 쪽지 — 예전엔 놓쳤다
    k1, k2 = "감사합니다", "확인했습니다"
    hidden = "늦어서 죄송합니다! 자료 첨부합니다."
    rows = [k1, k2, hidden, "아는1", "아는2", "아는3", "아는4", "아는5", "아는6"]
    got, _ = _run(rows, known=[k1, k2, "아는1", "아는2", "아는3", "아는4",
                               "아는5", "아는6"])
    check("아는 쪽지 두 개 아래의 새 쪽지를 놓치지 않는다",
          any("늦어서 죄송합니다" in b for b in got))

    # 5. 오늘 전달된 옛 공문이 위에 여럿 있어도 멈추지 않는다
    fwd = [_note(f"전달 공문 {i}", now - timedelta(days=20)) for i in range(5)]
    fresh = "오늘 온 새 쪽지입니다. 내일까지 회신 부탁드립니다."
    got, logs = _run(fwd + [fresh], known=[])
    check("옛 발신시간의 전달 쪽지 때문에 멈추지 않는다",
          any("오늘 온 새 쪽지" in b for b in got))
    check("최근(두 달 안) 전달 공문은 들인다",
          any("전달 공문 0" in b for b in got))

    # 6. 두 달 넘은 쪽지는 들이지 않는다
    ancient = _note("스테이크 솥밥 입니당!", now - timedelta(days=90))
    got, _ = _run([ancient, fresh], known=[],
                  since=now - timedelta(days=60))
    check("두 달 넘은 쪽지는 새로 들이지 않는다",
          not any("스테이크" in b for b in got))
    check("그 옆의 새 쪽지는 들인다", any("오늘 온 새 쪽지" in b for b in got))


def main():
    part_extract()
    part_stop()
    print()
    if FAILS:
        print("실패:", FAILS)
        sys.exit(1)
    print("전부 통과")


if __name__ == "__main__":
    main()
