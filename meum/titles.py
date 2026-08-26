# -*- coding: utf-8 -*-
"""
할 일의 '짧은 제목'과 '내 일인가 / 알아둘 일인가'를 정한다.

왜 필요한가
-----------
쪽지 문장을 그대로 제목으로 쓰면 이렇게 된다.

    점검사항 확인 후 수정된 평가계획을 8/19(수) 14시까지 보내주시기 바랍니다.

패널에서 세 줄을 잡아먹는데, 정작 알아야 할 것은 '평가계획 제출' 여섯 글자다.
원문은 그대로 보관하고, 화면에는 짧은 제목을 쓴다.

또 하나. 담임에게 오는 쪽지는 두 종류가 섞여 있다.

    · 내가 해야 할 일   — 평가계획 제출, 출결 정정, 회신
    · 알아둘 일         — 학생 대상 행사 안내, 급식 안내

둘을 같은 무게로 늘어놓으면 진짜 마감이 묻힌다. 그래서 갈라 둔다.
"""
from __future__ import annotations

import re
from typing import Optional

from . import dateparse

# 동작을 나타내는 말 → 제목에 쓸 짧은 명사
#
# 앞에 (?<![가-힣]) 를 붙이는 이유:
#   '수강신청 변경' 에서 '신청' 이 낱말 한가운데 걸리면
#   '수강 신청' 이 되어 정작 핵심인 '변경' 을 잃는다.
#   낱말이 시작되는 자리에서만 잡는다.
_ACTIONS = [
    (r"제출|송부|보내\s*주|보내주|올려\s*주|올려주|업로드|내주", "제출"),
    (r"회신|답장|답변\s*주|알려\s*주|알려주", "회신"),
    (r"변경|정정|취소|마감", "변경"),
    (r"확인|점검|검토|대조", "확인"),
    (r"작성|기재|입력|수정|보완", "작성"),
    (r"신청|접수|등록", "신청"),
    (r"참석|참여|출석", "참석"),
    (r"안내|홍보|공지|전달", "안내"),
]
ACTION_NOUN = [(re.compile(r"(?<![가-힣])(?:" + pat + r")"), noun)
               for pat, noun in _ACTIONS]

# 문장 끝의 존댓말 — 제목에서는 군더더기다
TAIL = re.compile(
    r"(?:해\s*)?(?:주시기\s*)?(?:바랍니다|바람|부탁\s*드립니다|부탁드려요|부탁합니다|"
    r"해\s*주세요|해주세요|주세요|주시면\s*감사하겠습니다|감사하겠습니다|"
    r"드립니다|합니다|하겠습니다|입니다|였습니다|있습니다)\s*[.!~]*\s*$")

# 문장 앞의 군더더기
HEAD = re.compile(
    r"^\s*(?:다만|그러나|하지만|또한|아울러|따라서|그리고|참고로|우선|먼저|"
    r"각\s*반에|담임\s*선생님(?:들)?께서(?:는|도)?|선생님(?:들)?께서(?:는|도)?|"
    r"선생님(?:들)?께|안녕하세요)\s*[,.]?\s*")

# 조사 '을/를' 의 위치 — 그 '바로 앞 몇 낱말'만 목적어로 본다.
# 문장 처음부터 끌어오면 '점검사항 확인 후 수정된 평가계획' 처럼 통째로 딸려온다.
PARTICLE = re.compile(r"(?:을|를)(?:\s|$)")
WORD = re.compile(r"[가-힣A-Za-z0-9·()]+")

# 학생 대상 행사로 읽히는 말
STUDENT_EVENT = re.compile(
    r"학생|아이들|참가자|희망자|수강생|대상자|특강|올림픽|체험교실|캠프|공모|대회|"
    r"프로그램|교실\s*운영|강연|심화교육|행사|주간|데이|캠페인")

# 나에게 시키는 신호
TO_ME = re.compile(
    r"제출|회신|답변|보내\s*주|보내주|올려\s*주|올려주|송부|입력|기재|작성|정정|"
    r"확인\s*(?:부탁|바|해)|점검|취합|명단|보고")


def _base(text: str) -> str:
    """날짜·군더더기만 걷어낸 상태. 동작 낱말을 찾을 때는 이걸 쓴다."""
    s = re.sub(r"\s+", " ", text or "").strip()
    s = dateparse.strip_datetime_tokens(s)
    # 날짜를 지운 자리에 '( )' 같은 빈 껍데기가 남는다
    s = re.sub(r"[(\[]\s*[)\]]", " ", s)
    # 그 바람에 홀로 남은 조사도 지운다 ("화요일 은" → "화요일")
    s = re.sub(r"\s+[은는이가]\s+", " ", s)
    # 시각을 지우면 '오늘 11시까지만' 이 '오늘 까지만' 이 된다 — 껍데기를 턴다
    s = re.sub(r"\s+까지(만|는)?\s*", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = HEAD.sub("", s)
    # 날짜는 어차피 목록에서 날짜별로 묶여 보이므로 제목에서는 뺀다
    s = re.sub(r"^\s*(?:오늘|내일|모레|금일|익일)\s*[은는,]?\s*", "", s)
    return s.strip()


def _strip(text: str) -> str:
    """위에 더해 문장 끝 존댓말까지 떼어낸 상태. 목적어를 찾을 때 쓴다."""
    s = _base(text)
    prev = None
    while prev != s:                 # 존댓말이 겹칠 수 있어 반복해서 떼어낸다
        prev = s
        s = TAIL.sub("", s).strip()
    return s.strip(" ,.·-\"'")


def _tail_words(text: str, n: int = 3) -> str:
    """문장 끝쪽 n 낱말만 남긴다 — 핵심은 대개 뒤에 있다."""
    words = WORD.findall(text or "")
    if not words:
        return ""
    picked = words[-n:]
    # 조사만 남은 토막은 버린다
    while picked and len(picked[0]) < 2:
        picked = picked[1:]
    return " ".join(picked).strip(" ,.·-")


def shorten(title: str, category: str = "", limit: int = 30) -> str:
    """
    긴 요청 문장을 '무엇 + 동작' 으로 줄인다.
    줄이지 못하면 뒤쪽 핵심 낱말만 남긴다(원문은 따로 보관한다).
    """
    s = _strip(title)
    # 동작 낱말은 존댓말을 떼기 전 문장에서 찾는다.
    # '보내주시기 바랍니다' 에서 끝을 떼면 '보내' 만 남아 '제출' 을 놓친다.
    full = _base(title)
    if not s:
        return (title or "")[:limit]

    # 1) '…을/를 … 보내주시기' → '평가계획 제출'
    #    조사가 여러 번 나오면 뒤쪽(동작에 가까운 것)을 쓴다
    for m in reversed(list(PARTICLE.finditer(s))):
        rest = full[m.end():] if m.end() <= len(full) else s[m.end():]
        noun = next((n for rx, n in ACTION_NOUN if rx.search(rest)), None)
        if not noun:
            continue
        obj = _tail_words(s[:m.start()], 3)
        if 2 <= len(obj) <= 22:
            return f"{obj} {noun}"[:limit]

    # 2) 목적어를 못 찾으면 동작 앞의 낱말 몇 개만 붙인다
    for rx, noun in ACTION_NOUN:
        m2 = rx.search(s)
        if not m2:
            continue
        head = s[:m2.start()]
        head = re.sub(r"(?:하여|관련하여|관련해서|에\s*대해|에\s*대하여)\s*$", "", head)
        head = _tail_words(head, 3)
        if 2 <= len(head) <= 22:
            return f"{head} {noun}"[:limit]
        break

    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "…"


def classify(title: str, detail: str = "", due_kind: str = "",
             category: str = "") -> str:
    """
    'mine'  — 내가 처리해야 할 일
    'notice' — 알아두면 되는 일 (학생 행사·일반 안내)
    """
    text = f"{title} {detail}"

    if TO_ME.search(text):
        return "mine"
    if due_kind == "event" and STUDENT_EVENT.search(text):
        return "notice"
    if category in ("참석", "안내") and not TO_ME.search(text):
        return "notice"
    if STUDENT_EVENT.search(text) and not TO_ME.search(text):
        return "notice"
    return "mine"
