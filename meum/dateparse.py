# -*- coding: utf-8 -*-
"""
한국어 마감 표현 → 절대 일시 정규화.

핵심 원칙: 기준일은 '프로그램 실행일'이 아니라 '쪽지 수신일'이다.
   ("내일까지" 라고 쓴 쪽지를 이틀 뒤에 처리해도 올바른 날짜가 나와야 한다)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Tuple

WEEKDAYS = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}

# 시각
_T_24H = re.compile(r"(?<![\d:])(\d{1,2})\s*시\s*(?:(\d{1,2})\s*분)?")
_T_COLON = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
_AMPM = re.compile(r"(오전|오후|저녁|아침)\s*(\d{1,2})\s*시?\s*(?:(\d{1,2})\s*분)?")

# 날짜
_D_SLASH = re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)")
_D_KOR = re.compile(r"(?:(\d{4})\s*년\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_D_DAY_ONLY = re.compile(r"(?<![\d/\-])(\d{1,2})\s*일(?!\s*간|\s*동안|\s*째)")
_D_ISO = re.compile(r"(?<!\d)(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})(?!\d)")
_D_DOT = re.compile(r"(?<!\d)(\d{1,2})\.\s*(\d{1,2})\.?(?!\d)")
_WD_PAREN = re.compile(r"\(\s*([월화수목금토일])\s*\)")

# 상대 표현
_REL_DAY = [
    (re.compile(r"오늘|금일"), 0),
    (re.compile(r"내일|익일|명일"), 1),
    (re.compile(r"모레|내일모레"), 2),
    (re.compile(r"글피"), 3),
]
_REL_WEEK = re.compile(r"(이번\s*주|금주|다음\s*주|차주|담주|내주)\s*([월화수목금토일])?\s*요?일?")
_REL_MONTH_END = re.compile(r"(이번\s*달|이달|당월|금월)\s*말|월말")

# 마감 신호
DEADLINE_HINTS = re.compile(
    r"까지|마감|기한|제출|회신|보내주|보내\s*주|송부|올려주|입력\s*바|완료\s*바|"
    r"부탁드립니다|바랍니다|요망|제출\s*바"
)
EVENT_HINTS = re.compile(r"회의|협의회|연수|행사|워크숍|워크샵|간담회|설명회|점검|방문|실시|개최|진행")


@dataclass
class ParsedDue:
    due_date: Optional[date] = None
    due_time: Optional[time] = None
    kind: str = "none"          # deadline | event | none
    matched: str = ""           # 근거가 된 원문 조각
    warn: str = ""              # 요일 불일치 등 경고

    @property
    def iso(self) -> Optional[str]:
        if not self.due_date:
            return None
        if self.due_time:
            return datetime.combine(self.due_date, self.due_time).isoformat(timespec="minutes")
        return self.due_date.isoformat()


def _nearest_year(base: date, month: int, day: int) -> Optional[date]:
    """연도 없는 월/일 → 기준일에서 가장 가까운 해로 보정."""
    for y in (base.year, base.year + 1, base.year - 1):
        try:
            cand = date(y, month, day)
        except ValueError:
            continue
        delta = (cand - base).days
        if -180 <= delta <= 300:
            return cand
    try:
        return date(base.year, month, day)
    except ValueError:
        return None


def _extract_time(text: str) -> Optional[time]:
    m = _AMPM.search(text)
    if m:
        period, h, mi = m.group(1), int(m.group(2)), int(m.group(3) or 0)
        if period in ("오후", "저녁") and h < 12:
            h += 12
        if period in ("오전", "아침") and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return time(h, mi)
    m = _T_COLON.search(text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return time(h, mi)
    m = _T_24H.search(text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return time(h, mi)
    return None


def _extract_date(text: str, base: date) -> tuple:
    """(date, 근거문자열) 반환."""
    m = _D_ISO.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(0)
        except ValueError:
            pass

    m = _D_KOR.search(text)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        if y:
            try:
                return date(int(y), mo, d), m.group(0)
            except ValueError:
                pass
        else:
            r = _nearest_year(base, mo, d)
            if r:
                return r, m.group(0)

    m = _D_SLASH.search(text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            r = _nearest_year(base, mo, d)
            if r:
                return r, m.group(0)

    m = _D_DOT.search(text)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            r = _nearest_year(base, mo, d)
            if r:
                return r, m.group(0)

    # 상대 표현
    for rx, delta in _REL_DAY:
        if rx.search(text):
            return base + timedelta(days=delta), rx.search(text).group(0)

    m = _REL_WEEK.search(text)
    if m:
        head, wd = m.group(1), m.group(2)
        monday = base - timedelta(days=base.weekday())
        if re.search(r"다음|차주|담주|내주", head):
            monday += timedelta(days=7)
        target = monday + timedelta(days=WEEKDAYS[wd]) if wd else monday + timedelta(days=4)
        return target, m.group(0)

    if _REL_MONTH_END.search(text):
        nxt = date(base.year + (base.month == 12), (base.month % 12) + 1, 1)
        return nxt - timedelta(days=1), _REL_MONTH_END.search(text).group(0)

    # '19일' 처럼 일자만
    m = _D_DAY_ONLY.search(text)
    if m:
        d = int(m.group(1))
        for mo_off in (0, 1):
            mo = base.month + mo_off
            y = base.year + (mo > 12)
            mo = mo - 12 if mo > 12 else mo
            try:
                cand = date(y, mo, d)
            except ValueError:
                continue
            if cand >= base - timedelta(days=3):
                return cand, m.group(0)

    return None, ""


def find_dates(text: str, base: date) -> List[Tuple[date, str]]:
    """한 줄에 들어 있는 날짜를 모두 찾는다 ('8/26(수), 9/16(수)' → 2건)."""
    found: List[Tuple[date, str]] = []
    seen = set()

    def add(d: Optional[date], raw: str):
        if d and d not in seen:
            seen.add(d)
            found.append((d, raw))

    for m in _D_ISO.finditer(text):
        try:
            add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(0))
        except ValueError:
            pass
    for m in _D_KOR.finditer(text):
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        try:
            add(date(int(y), mo, d) if y else _nearest_year(base, mo, d), m.group(0))
        except ValueError:
            pass
    for m in _D_SLASH.finditer(text):
        mo, d = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            add(_nearest_year(base, mo, d), m.group(0))
    return sorted(found, key=lambda x: x[0])


def extract_time(text: str) -> Optional[time]:
    """공개 래퍼 — 한 줄에서 시각을 찾는다."""
    return _extract_time(text)


def strip_datetime_tokens(text: str) -> str:
    """제목을 만들기 위해 날짜·시각·요일 표기를 걷어낸다."""
    s = text
    for rx in (_D_ISO, _D_KOR, _D_SLASH, _D_DOT, _T_COLON, _T_24H, _AMPM, _WD_PAREN):
        s = rx.sub(" ", s)
    s = re.sub(r"^[\s#*▶●○\-–—·•>]+", "", s)
    s = re.sub(r"[\s,·]+", " ", s)
    return s.strip(" ,.-–—·")


def parse_due(text: str, received_at: datetime,
              default_deadline_time: str = "17:00") -> ParsedDue:
    """본문에서 마감/일정을 뽑아낸다. 기준일은 수신일."""
    if not text:
        return ParsedDue()
    base = received_at.date()
    res = ParsedDue()

    # 마감 신호가 있는 문장을 우선 검사.
    # 단, 문장 분리기가 '9.3.' 같은 날짜의 마침표에서 잘라버릴 수 있으므로
    # 아무 문장에서도 못 찾으면 본문 전체를 한 번 더 훑는다.
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    hinted = [s for s in sentences if DEADLINE_HINTS.search(s)]
    candidates = hinted + [s for s in sentences if s not in hinted] + [text]

    for sent in candidates:
        d, matched = _extract_date(sent, base)
        if not d:
            continue
        res.due_date = d
        res.matched = matched
        # 시각은 반드시 '그 날짜가 있는 문장'에서만 가져온다.
        # 본문 전체에서 찾으면 무관한 줄의 시각이 딸려온다
        # (행사 안내 쪽지에서 다른 행사의 16:00 이 끌려온 사례 있음)
        res.due_time = _extract_time(sent)
        scope = sent if DEADLINE_HINTS.search(sent) else text
        res.kind = "deadline" if DEADLINE_HINTS.search(scope) else (
            "event" if EVENT_HINTS.search(scope) else "deadline")
        # 요일 검증: '8/19(수)' 의 (수) 와 실제 요일 대조
        wd = _WD_PAREN.search(sent) or _WD_PAREN.search(text)
        if wd:
            want = WEEKDAYS[wd.group(1)]
            if d.weekday() != want:
                names = "월화수목금토일"
                res.warn = (f"본문은 ({wd.group(1)})라고 적혀 있으나 "
                            f"{d.isoformat()}은 {names[d.weekday()]}요일입니다. 확인 필요")
        break

    if res.due_date and not res.due_time and res.kind == "deadline":
        hh, mm = default_deadline_time.split(":")
        res.due_time = time(int(hh), int(mm))

    if not res.due_date:
        res.kind = "none"
    return res
