# -*- coding: utf-8 -*-
"""
홍보용 촬영에 쓸 '가짜 쪽지' 를 만든다.

실제 쪽지는 다른 선생님들의 업무 내용이라 한 프레임도 쓸 수 없다.
그래서 LOCALAPPDATA 를 임시 폴더로 돌려 완전히 분리된 곳에
가짜 자료만 넣고, 그 상태의 패널을 찍는다.
(실제 %LOCALAPPDATA%\\메움 은 건드리지 않는다)

    python tools/demo_data.py <임시폴더>
"""
import os
import sys
from datetime import date, datetime, timedelta

if len(sys.argv) < 2:
    print("사용법: python tools/demo_data.py <임시폴더>")
    raise SystemExit(1)

os.environ["LOCALAPPDATA"] = sys.argv[1]        # 반드시 import 보다 먼저
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from meum import config          # noqa: E402
from meum.state import State     # noqa: E402

config.ensure_dirs()
print("데모 자료 위치 :", config.APP_DIR)

today = date.today()


def at(days, hh=None, mm=0):
    d = today + timedelta(days=days)
    return d.isoformat() if hh is None else \
        datetime(d.year, d.month, d.day, hh, mm).isoformat(timespec="minutes")


# (발신자, 부서, 제목, 본문 한 줄, 할 일들)
DEMO = [
    ("김민수", "교육과정부", "2학기 평가계획 수정본 제출 안내",
     "점검사항 반영한 평가계획 수정본을 오늘 16시까지 제출 부탁드립니다.",
     [("2학기 평가계획 수정본 제출", at(0, 16), "제출", 0.92, "mine")]),

    ("이서연", "학생안전부", "2학기 학급 자치회 조직도",
     "-첨부파일의 학급자치회 조직도를 작성하셔서 8/31(월) 17시까지 회신 부탁드립니다.",
     [("학급자치회 조직도 회신", at(0, 17), "제출", 0.90, "mine")]),

    ("박지훈", "정보부", "교무실 보안점검표 작성",
     "이번 주 금요일까지 교무실 보안점검표 작성해 주시기 바랍니다.",
     [("교무실 보안점검표 작성", at(1, 17), "작성", 0.86, "mine")]),

    ("최유진", "교육연구부", "학부모 상담주간 신청 취합",
     "학급별 상담 신청 인원을 취합해 회신해 주세요.",
     [("학부모 상담주간 신청 취합", at(2, 15), "제출", 0.88, "mine")]),

    ("정하람", "학생안전부", "임명장 수여식 및 대의원회",
     "9월 4일(금) 13시 20분부터 시청각실에서 임명장 수여식이 있습니다.",
     [("임명장 수여식 참석", at(4, 13, 20), "참석", 0.80, "notice")]),

    ("강도윤", "교육연구부", "독서활동 입력 안내",
     "1학기 독서활동 입력을 마감일까지 완료해 주시기 바랍니다.",
     [("독서활동 입력", at(-1, 17), "작성", 0.85, "mine")]),
]

st = State()
st.con.execute("DELETE FROM tasks")
st.con.execute("DELETE FROM messages")

for i, (name, org, subject, body, tasks) in enumerate(DEMO):
    msg_id = f"demo-{i:02d}"
    st.upsert_message({
        "source": "goe" if i % 2 else "brity",
        "msg_id": msg_id,
        "list_key": msg_id,
        "thread_key": f"t{i}",
        "subject": subject,
        "sender": name,
        "sender_org": org,
        "received_at": datetime.now().isoformat(timespec="seconds"),
        "body_latest": body,
        "body_raw": body,
        "attachments": "",
        "processed_at": datetime.now().isoformat(timespec="seconds"),
    })
    for title, due, cat, conf, kind in tasks:
        # short_title·kind 는 나중에 덧붙인 칸이라 add_task 가 받지 않는다.
        # 넣은 뒤 따로 채운다.
        tid = st.add_task({
            "msg_id": msg_id, "source": "goe" if i % 2 else "brity",
            "thread_key": f"t{i}",
            "title": title, "detail": body, "due_at": due,
            "due_kind": "deadline", "category": cat,
            "requester": f"{name}({org})", "confidence": conf,
            "status": "approved", "warn": "",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        st.con.execute("UPDATE tasks SET short_title=?, kind=? WHERE task_id=?",
                       (title, kind, tid))

st.con.commit()
n_m = st.con.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"]
n_t = st.con.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
st.close()
print(f"가짜 쪽지 {n_m}건 · 할 일 {n_t}건 준비 완료")
