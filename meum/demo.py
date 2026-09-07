# -*- coding: utf-8 -*-
"""
연수·시연용 가짜 자료.

연수장 컴퓨터에는 브리티도, 쪽지도 없다. 그래서 시연 모드(--demo)는
LOCALAPPDATA 를 임시 폴더로 돌린 뒤(run.py 가 import 전에 한다) 이
가짜 자료를 채워, 어느 컴퓨터에서든 채워진 패널을 바로 보여 준다.

이름·부서·내용 전부 지어낸 것이다. 실제 쪽지는 한 글자도 없다.
날짜는 '오늘' 기준 상대값이라 언제 시연해도 빨간 오늘 배너·깜빡한 것·
달력 점이 살아 있는 모습으로 나온다.
"""
from datetime import date, datetime, timedelta

from . import config
from .state import State


def _at(days, hh=None, mm=0):
    d = date.today() + timedelta(days=days)
    if hh is None:
        return d.isoformat()
    return datetime(d.year, d.month, d.day, hh, mm).isoformat(timespec="minutes")


# (발신자, 부서, 제목, 본문 한 줄, [(할 일, 마감, 갈래, 확신도, 종류)])
_DEMO = [
    ("김민수", "교육과정부", "2학기 평가계획 수정본 제출 안내",
     "점검사항 반영한 평가계획 수정본을 오늘 16시까지 제출 부탁드립니다.",
     [("2학기 평가계획 수정본 제출", _at(0, 16), "제출", 0.92, "mine")]),
    ("이서연", "학생안전부", "2학기 학급 자치회 조직도",
     "첨부파일의 학급자치회 조직도를 작성하셔서 오늘 17시까지 회신 부탁드립니다.",
     [("학급자치회 조직도 회신", _at(0, 17), "제출", 0.90, "mine")]),
    ("박지훈", "정보부", "교무실 보안점검표 작성",
     "이번 주 금요일까지 교무실 보안점검표 작성해 주시기 바랍니다.",
     [("교무실 보안점검표 작성", _at(1, 17), "작성", 0.86, "mine")]),
    ("최유진", "교육연구부", "학부모 상담주간 신청 취합",
     "학급별 상담 신청 인원을 취합해 회신해 주세요.",
     [("학부모 상담주간 신청 취합", _at(2, 15), "제출", 0.88, "mine")]),
    ("정하람", "학생안전부", "임명장 수여식 및 대의원회",
     "다음 주 금요일 13시 20분부터 시청각실에서 임명장 수여식이 있습니다.",
     [("임명장 수여식 참석", _at(4, 13, 20), "참석", 0.80, "notice")]),
    ("강도윤", "교육연구부", "독서활동 입력 안내",
     "1학기 독서활동 입력을 마감일까지 완료해 주시기 바랍니다.",
     [("독서활동 입력", _at(-1, 17), "작성", 0.85, "mine")]),
]


def seed() -> tuple:
    """가짜 쪽지·할 일·메모·학사일정을 채운다. (쪽지수, 할일수) 반환."""
    config.ensure_dirs()
    st = State()
    st.con.execute("DELETE FROM tasks")
    st.con.execute("DELETE FROM messages")
    st.con.execute("DELETE FROM memos")
    st.con.execute("DELETE FROM school_events")

    now = datetime.now().isoformat(timespec="seconds")
    for i, (name, org, subject, body, tasks) in enumerate(_DEMO):
        msg_id = f"demo-{i:02d}"
        st.upsert_message({
            "source": "goe" if i % 2 else "brity",
            "msg_id": msg_id, "list_key": msg_id, "thread_key": f"t{i}",
            "subject": subject, "sender": name, "sender_org": org,
            "received_at": now, "body_latest": body, "body_raw": body,
            "attachments": "", "processed_at": now,
        })
        for title, due, cat, conf, kind in tasks:
            tid = st.add_task({
                "msg_id": msg_id, "source": "goe" if i % 2 else "brity",
                "thread_key": f"t{i}", "title": title, "detail": body,
                "due_at": due, "due_kind": "deadline", "category": cat,
                "requester": f"{name}({org})", "confidence": conf,
                "status": "approved", "warn": "", "created_at": now,
            })
            st.con.execute(
                "UPDATE tasks SET short_title=?, kind=? WHERE task_id=?",
                (title, kind, tid))

    # 달력 메모와 학사일정도 한 점씩 — 시연에서 보여 줄 것들
    st.add_memo(_at(1), "수행평가 채점 마저 하기")
    st.add_memo(_at(3), "동아리 발표회 준비물 챙기기")
    st.add_school_event("2학기 중간고사", _at(7), _at(10), category="시험")

    st.con.commit()
    n_m = st.con.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"]
    n_t = st.con.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
    st.close()
    return n_m, n_t
