# -*- coding: utf-8 -*-
"""
할 일 추출 엔진.

두 가지 구현을 교체 가능한 형태로 둔다.
  · RuleExtractor  — 규칙 기반. 외부 전송 없음. 기본값.
  · ClaudeExtractor — Claude API. 정확도 향상. 본문이 외부로 전송되므로
                      보안 검토 후에만 사용한다.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, time as dtime
from typing import List, Optional

from . import dateparse, titles

QUOTE_MARKERS = [
    r"-{3,}\s*Original Message\s*-{3,}",
    r"-{3,}\s*원본\s*메시지\s*-{3,}",      # 브리티 · GOE 공통
    r"^\s*Sender\s*:",
    r"^\s*발\s*신\s*자\s*:",              # GOE 인용부 머리글
]
QUOTE_RE = re.compile("|".join(QUOTE_MARKERS), re.IGNORECASE | re.MULTILINE)

REQUEST_VERBS = re.compile(
    r"부탁드립니다|부탁드려요|바랍니다|주시기 바랍|주시기바랍|해주세요|해 주세요|"
    r"제출|회신|답변|확인|점검|작성|입력|참석|참여|신청|등록|송부|보내주|올려주|요망"
)
NOTICE_ONLY = re.compile(r"안내드립니다|안내입니다|공지드립니다|참고하시기|알려드립니다")

CATEGORY_RULES = [
    ("제출", re.compile(r"제출|송부|보내주|보내 주|올려주|업로드")),
    ("회신", re.compile(r"회신|답변|답장|의견\s*주|알려주")),
    ("확인", re.compile(r"확인|점검|검토|대조")),
    ("참석", re.compile(r"참석|참여|출석|방문")),
    ("작성", re.compile(r"작성|기재|입력|등록|신청")),
    ("안내", re.compile(r"안내|공지|알림")),
]

# 주의: \b 는 한글 앞뒤에서 경계로 잡히지 않는다("…5314로" 처리 실패).
#       따라서 숫자 경계만 직접 단속한다.
PHONE_RE = re.compile(r"(?<!\d)0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")
RRN_RE = re.compile(r"(?<!\d)\d{6}\s*-\s*\d{7}(?!\d)")

# '무엇을 하라'는 구체적 행위 동사 (막연한 '바랍니다'와 구분)
CONCRETE_ACTION = re.compile(
    r"제출|회신|답변|답장|확인|점검|검토|작성|기재|입력|등록|신청|참석|참여|"
    r"송부|보내주|보내 주|올려주|업로드|수정|보완")

# 요청형 어미 — 배경 설명 문장과 실제 요청 문장을 가른다
REQUEST_ENDING = re.compile(
    r"부탁드립니다|부탁드려요|부탁합니다|바랍니다|바라며|주시기|해주세요|해 주세요|"
    r"주세요|요망|주시면|주십시오")


@dataclass
class ExtractedTask:
    title: str
    detail: str = ""
    due_at: Optional[str] = None
    due_kind: str = "none"
    category: str = "안내"
    requester: str = ""
    confidence: float = 0.0
    warn: str = ""
    evidence: str = ""
    kind: str = "mine"          # mine(내가 할 일) | notice(알아둘 일)
    short_title: str = ""       # 화면에 쓸 짧은 제목

    def to_row(self, msg_id: str, thread_key: str, status: str) -> dict:
        return {
            "msg_id": msg_id,
            "source": "brity",
            "thread_key": thread_key,
            "title": self.title,
            "detail": self.detail,
            "due_at": self.due_at,
            "due_kind": self.due_kind,
            "requester": self.requester,
            "category": self.category,
            "confidence": self.confidence,
            "status": status,
            "kind": self.kind or "mine",
            "short_title": self.short_title or self.title[:40],
            "warn": self.warn,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }


# --------------------------------------------------------------------------
# 전처리
# --------------------------------------------------------------------------
def strip_quotes(body: str) -> str:
    """인용부(---- Original Message ----) 이후를 잘라 최신 발화만 남긴다."""
    if not body:
        return ""
    m = QUOTE_RE.search(body)
    return body[:m.start()].strip() if m else body.strip()


def normalize_thread_key(subject: str, sender: str) -> str:
    s = re.sub(r"^\s*(RE|FW|답장|전달)\s*(\(\d+\))?\s*:\s*", "", subject or "",
               flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()[:60]
    return f"{s}|{sender}"


def mask_sensitive(text: str) -> str:
    text = PHONE_RE.sub("[전화번호]", text)
    text = RRN_RE.sub("[주민번호]", text)
    return text


def looks_actionable(text: str) -> bool:
    return bool(REQUEST_VERBS.search(text or ""))


def has_date_signal(text: str) -> bool:
    return bool(re.search(
        r"\d{1,2}\s*/\s*\d{1,2}|\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}\s*일|"
        r"오늘|내일|모레|금일|익일|다음\s*주|차주|이번\s*주|까지|마감|기한",
        text or ""))


# --------------------------------------------------------------------------
# 규칙 기반 추출기
# --------------------------------------------------------------------------
class RuleExtractor:
    name = "rule"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def extract(self, *, subject: str, body: str, sender: str, sender_org: str,
                received_at: datetime) -> List[ExtractedTask]:
        latest = strip_quotes(body)
        if not latest:
            return []

        actionable = looks_actionable(latest)
        dated = has_date_signal(latest)
        if not actionable and not dated:
            return []

        # 행사 안내처럼 한 쪽지에 여러 일정이 열거된 경우를 먼저 처리한다.
        multi = self._extract_event_list(latest, sender, sender_org, received_at)
        if multi:
            return multi

        due = dateparse.parse_due(
            latest, received_at,
            default_deadline_time=self.cfg.get("deadline_default_time", "17:00"))

        category = "안내"
        for cname, rx in CATEGORY_RULES:
            if rx.search(latest):
                category = cname
                break

        title = self._make_title(subject, latest, category, due.matched)
        requester = f"{sender}({sender_org})" if sender_org else sender

        conf = self._confidence(actionable, due, latest)

        detail = self._make_detail(latest)
        return [ExtractedTask(
            title=title,
            detail=detail,
            due_at=due.iso,
            due_kind=due.kind,
            category=category,
            requester=requester,
            confidence=conf,
            warn=due.warn,
            evidence=due.matched,
            short_title=titles.shorten(title, category),
            kind=titles.classify(title, detail, due.kind, category),
        )]

    # ---- 여러 일정이 열거된 쪽지 ----
    def _extract_event_list(self, body: str, sender: str, sender_org: str,
                            received_at: datetime) -> List[ExtractedTask]:
        """
        '#8/28(금) 16:00 과학명사특강' 처럼 줄마다 일정이 나열된 쪽지를 처리한다.

        머리글 줄(날짜를 포함하고 '-'로 시작하지 않는 줄)마다 일정 하나를 만들고,
        '#8/26(수), 9/16(수)' 처럼 날짜가 둘이면 각각 별도 일정으로 나눈다.
        """
        base = received_at.date()
        headers = []
        for raw in body.split("\n"):
            s = raw.strip()
            if not s:
                continue
            dates = dateparse.find_dates(s, base)
            if not dates:
                continue

            # '-' 로 시작하는 줄은 대개 윗줄 행사의 부연 설명이라 건너뛴다.
            # 그러나 공문 쪽지에서 '-' 는 **지시사항을 적는 자리**이기도 하다.
            #   -첨부파일의 조직도를 작성하셔서 … 8/31 17시까지 회신★부탁드립니다
            # 예전에는 이런 줄을 통째로 버려, '-' 뒤에 적힌 마감은 하나도 잡지
            # 못했다. 우연히 놓친 것이 아니라 늘 놓치고 있었다.
            # 그래서 날짜에 더해 **구체적인 행동**(제출·회신·작성 …)과 요청이
            # 함께 있을 때만 그 줄도 일정으로 본다.
            # '참고 부탁드립니다' 같은 배경 설명까지 일정으로 만들면
            # 목록이 문장 조각으로 뒤덮인다(시험이 그렇게 잡아냈다).
            if s.startswith(("-", "–", "—", "·", "•")):
                if not (CONCRETE_ACTION.search(s)
                        and (REQUEST_ENDING.search(s) or "까지" in s)):
                    continue

            title = dateparse.strip_datetime_tokens(s)
            if len(title) < 3:
                continue
            headers.append((s, dates, title))

        # 두 건 이상 나열돼 있을 때만 '행사 목록'으로 본다
        if len(headers) < 2:
            return []

        requester = f"{sender}({sender_org})" if sender_org else sender
        out: List[ExtractedTask] = []
        for line, dates, title in headers:
            t = dateparse.extract_time(line)          # 반드시 같은 줄에서만
            is_deadline = bool(REQUEST_ENDING.search(line) and CONCRETE_ACTION.search(line))
            for d, raw in dates:
                if t:
                    due_at = datetime.combine(d, t).isoformat(timespec="minutes")
                elif is_deadline:
                    hh, mm = self.cfg.get("deadline_default_time", "17:00").split(":")
                    due_at = datetime.combine(d, dtime(int(hh), int(mm))).isoformat(
                        timespec="minutes")
                else:
                    due_at = d.isoformat()            # 시각 미상 → 종일 일정
                warn = self._weekday_warn(line, d)
                out.append(ExtractedTask(
                    title=title[:80],
                    short_title=titles.shorten(title),
                    kind=titles.classify(title, line, "event",
                                         "참석" if not is_deadline else "제출"),
                    detail=line[:300],
                    due_at=due_at,
                    due_kind="deadline" if is_deadline else "event",
                    category="참석" if not is_deadline else "제출",
                    requester=requester,
                    # 안내성 행사이므로 자동 등록하지 않고 교사가 고르게 한다
                    confidence=0.70 if not warn else 0.55,
                    warn=warn,
                    evidence=raw,
                ))
        return out

    @staticmethod
    def _weekday_warn(line: str, d) -> str:
        m = re.search(r"\(\s*([월화수목금토일])\s*\)", line)
        if not m:
            return ""
        names = "월화수목금토일"
        want = names.index(m.group(1))
        if d.weekday() != want:
            return (f"본문은 ({m.group(1)})라고 적혀 있으나 "
                    f"{d.isoformat()}은 {names[d.weekday()]}요일입니다. 확인 필요")
        return ""

    # ---- 내부 ----
    def _make_title(self, subject: str, body: str, category: str,
                    evidence: str = "") -> str:
        subj = re.sub(r"^\s*(RE|FW|답장|전달)\s*(\(\d+\))?\s*:\s*", "", subject or "",
                      flags=re.IGNORECASE).strip()

        # 1순위: 마감일이 들어 있는 문장. 그것이 곧 '해야 할 일'이다.
        #        줄바꿈으로 문장이 잘리는 경우가 많아 본문을 한 줄로 편 뒤 잘라낸다.
        if evidence:
            flat = re.sub(r"\s*\n\s*", " ", body)
            idx = flat.find(evidence)
            if idx >= 0:
                left = max((flat.rfind(p, 0, idx) for p in ".!?"), default=-1)
                right = min((r for r in (flat.find(p, idx) for p in ".!?") if r >= 0),
                            default=-1)
                start = left + 1
                end = right + 1 if right >= 0 else len(flat)
                cand = re.sub(r"\s+", " ", flat[start:end]).strip()
                if 8 <= len(cand) <= 120:
                    return cand[:80]

        # 2순위: '구체적 행위 + 요청형 어미' 문장 → 그것이 진짜 요청이다.
        #        (배경 설명 문장에도 '답변/확인' 같은 단어가 섞이므로 어미로 가른다)
        sents = [re.sub(r"\s+", " ", s).strip()
                 for s in re.split(r"(?<=[.!?])\s+|\n+", body)]
        sents = [s for s in sents
                 if not (NOTICE_ONLY.search(s) and not CONCRETE_ACTION.search(s))]

        for want_ending in (True, False):
            for s in sents:
                if not (8 <= len(s) <= 100) or not CONCRETE_ACTION.search(s):
                    continue
                if want_ending and not REQUEST_ENDING.search(s):
                    continue
                return s[:80]

        if subj:
            return f"{subj[:55]} — {category}"
        return re.sub(r"\s+", " ", body)[:60]

    def _make_detail(self, body: str) -> str:
        s = re.sub(r"\s*\n\s*", " ", body).strip()
        return s[:300]

    def _confidence(self, actionable: bool, due: dateparse.ParsedDue, body: str) -> float:
        c = 0.30
        if actionable:
            c += 0.25
        if CONCRETE_ACTION.search(body):
            c += 0.10          # 막연한 '바랍니다'가 아니라 구체적 행위 요청
        if due.due_date:
            c += 0.20
            if due.matched and re.search(r"\d", due.matched):
                c += 0.10      # 명시적 날짜 표기
            if re.search(r"까지", body):
                c += 0.08
        else:
            c -= 0.10          # 마감이 없으면 교사가 직접 정해야 함
        if NOTICE_ONLY.search(body):
            c -= 0.30          # '안내드립니다/참고하시기'는 강한 공지 신호
        if due.warn:
            c -= 0.20
        return round(max(0.05, min(0.97, c)), 2)


# --------------------------------------------------------------------------
# Claude 기반 추출기 (선택)
# --------------------------------------------------------------------------
SYSTEM_PROMPT = """당신은 한국 고등학교 교사의 업무 비서입니다.
브리티 메신저 쪽지 본문에서 '교사가 해야 할 일'과 '마감일시'를 뽑아냅니다.

규칙:
- 단순 안내·공지는 is_actionable=false 로 처리합니다.
- 날짜 기준일은 '수신일시'입니다. '내일'은 수신일 기준 다음 날입니다.
- 연도가 없는 날짜(8/19 등)는 수신일 기준 가장 가까운 날짜로 해석합니다.
- 마감 시각이 명시되지 않은 deadline 은 due_time 을 null 로 두세요.
- 확신이 낮으면 confidence 를 낮게 주세요. 지어내지 마세요.
"""

TOOL_SCHEMA = {
    "name": "report_tasks",
    "description": "쪽지에서 추출한 할 일 목록을 보고한다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_actionable": {"type": "boolean"},
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "detail": {"type": "string"},
                        "due_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                        "due_time": {"type": ["string", "null"], "description": "HH:MM"},
                        "due_kind": {"type": "string", "enum": ["deadline", "event", "none"]},
                        "category": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["title", "due_kind", "confidence"],
                },
            },
        },
        "required": ["is_actionable", "tasks"],
    },
}


class ClaudeExtractor:
    name = "claude"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.fallback = RuleExtractor(cfg)
        key = cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        self.client = None
        if key:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=key)
            except Exception:
                self.client = None

    def extract(self, *, subject: str, body: str, sender: str, sender_org: str,
                received_at: datetime) -> List[ExtractedTask]:
        latest = strip_quotes(body)
        if not latest:
            return []
        if self.client is None:
            return self.fallback.extract(subject=subject, body=body, sender=sender,
                                         sender_org=sender_org, received_at=received_at)
        # 1차 필터로 호출량 절감
        if not (looks_actionable(latest) or has_date_signal(latest)):
            return []

        payload = latest
        if self.cfg.get("mask_phone_numbers", True):
            payload = mask_sensitive(payload)

        user = (
            f"수신일시: {received_at.isoformat(timespec='minutes')}\n"
            f"발신자: {sender} ({sender_org})\n"
            f"제목: {subject}\n"
            f"본문:\n{payload}\n"
        )
        try:
            resp = self.client.messages.create(
                model=self.cfg.get("claude_model", "claude-sonnet-5"),
                max_tokens=1200,
                system=SYSTEM_PROMPT,
                tools=[TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": "report_tasks"},
                messages=[{"role": "user", "content": user}],
            )
            data = None
            for block in resp.content:
                if getattr(block, "type", "") == "tool_use":
                    data = block.input
                    break
            if not data or not data.get("is_actionable"):
                return []
            out = []
            for t in data.get("tasks", []):
                due_at = None
                if t.get("due_date"):
                    due_at = t["due_date"]
                    if t.get("due_time"):
                        due_at = f"{t['due_date']}T{t['due_time']}"
                    elif t.get("due_kind") == "deadline":
                        due_at = f"{t['due_date']}T{self.cfg.get('deadline_default_time','17:00')}"
                out.append(ExtractedTask(
                    title=t.get("title", "")[:80],
                    detail=t.get("detail", "")[:300],
                    due_at=due_at,
                    due_kind=t.get("due_kind", "none"),
                    category=t.get("category", "안내"),
                    requester=f"{sender}({sender_org})" if sender_org else sender,
                    confidence=float(t.get("confidence", 0.5)),
                ))
            return out
        except Exception:
            return self.fallback.extract(subject=subject, body=body, sender=sender,
                                         sender_org=sender_org, received_at=received_at)


def build(cfg: dict):
    if cfg.get("extractor") == "claude":
        return ClaudeExtractor(cfg)
    return RuleExtractor(cfg)
