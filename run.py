# -*- coding: utf-8 -*-
"""
메움 — 메신저에서 놓친 선생님들의 업무를 메워드립니다.

    메움.exe                 처음이면 설치 마법사, 이후엔 할 일 패널
    메움.exe --setup         설치 마법사 다시 열기
    메움.exe --widget        바탕화면 할 일 패널 (기본과 같음)
    메움.exe --collect       지금 당장 쪽지 정리 (확인 창을 띄움)
    메움.exe --calendar      달력
    메움.exe --trigger daily 작업 스케줄러가 호출하는 형태
    메움.exe --list-only     목록만 읽기 (아무것도 바꾸지 않음)
    메움.exe --status        실행 이력 확인
    메움.exe --uninstall     자동 실행 등록만 해제
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from meum import config                      # noqa: E402
from meum.app import Runner, setup_logging   # noqa: E402
from meum.state import State                 # noqa: E402


def out(*a):
    """창 모드(--noconsole)로 빌드하면 stdout 이 없으므로 감싸서 쓴다."""
    if sys.stdout is None:
        return
    try:
        print(*a)
    except Exception:
        pass


def cmd_list_only() -> int:
    from meum.collector import BrityCollector
    cfg = config.load()
    log = setup_logging()
    c = BrityCollector(cfg, log=log.info)
    try:
        c.attach()
        me = c.detect_my_name()
        if me:
            out(f"로그인 사용자: {me}")
        notes = c.list_notes()
        out(f"\n쪽지함 {len(notes)}건 (읽기 전용, 아무것도 변경하지 않았습니다)\n")
        for n in notes:
            flag = " [첨부]" if n.has_attach else ""
            when = n.approx_dt.strftime("%Y-%m-%d") if n.approx_dt else n.date_text
            out(f"  {when}  {n.sender:<8}{flag}  {n.preview[:56]}")
        return 0
    finally:
        c.restore()


def cmd_status() -> int:
    from meum.calendar_sync import GoogleBackend
    cfg = config.load()
    st = State()
    lr = st.last_run_at
    out(f"마지막 성공 실행: {lr:%Y-%m-%d %H:%M}" if lr else "마지막 성공 실행: 없음")
    out(f"저장 위치      : {', '.join(cfg.get('calendar_backends', ['ics']))}")
    out(f"Google 연결    : {'됨' if GoogleBackend.is_authorized() else '안 됨'}")
    out(f"수집 보관 쪽지 : "
          f"{st.con.execute('SELECT COUNT(*) c FROM messages').fetchone()['c']}건")
    out(f"등록된 할 일   : "
          f"{st.con.execute('SELECT COUNT(*) c FROM tasks').fetchone()['c']}건")
    out("\n최근 실행 이력")
    rows = st.con.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT 10").fetchall()
    if not rows:
        out("  (없음)")
    for r in rows:
        out(f"  {r['started_at']}  {r['trigger']:<8} {r['status']:<8} "
              f"수집 {r['collected']} 추출 {r['extracted']} 저장 {r['synced']}"
              + (f"  · {(r['error'] or '')[:50]}" if r["error"] else ""))
    st.close()
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="메움",
                                description="메움 — 메신저에서 놓친 선생님들의 업무를 메워드립니다")
    p.add_argument("--trigger", default="manual",
                   choices=["manual", "daily", "logon", "extra", "watch"])
    p.add_argument("--setup", action="store_true", help="설치 마법사 열기")
    p.add_argument("--headless", action="store_true", help="확인 창 없이 실행")
    p.add_argument("--list-only", action="store_true", help="목록만 읽고 종료")
    p.add_argument("--status", action="store_true", help="실행 이력 확인")
    p.add_argument("--force", action="store_true", help="오늘 이미 실행했어도 다시 실행")
    p.add_argument("--uninstall", action="store_true", help="자동 실행 등록 해제")
    p.add_argument("--widget", action="store_true", help="바탕화면 할 일 패널 열기")
    p.add_argument("--collect", action="store_true",
                   help="지금 쪽지를 정리한다 (확인 창을 띄움)")
    p.add_argument("--calendar", action="store_true", help="달력 열기")
    args = p.parse_args()

    if args.calendar:
        from meum.calendar_view import show
        show()
        return 0
    if args.widget:
        from meum.widget import show
        show()
        return 0
    if args.status:
        return cmd_status()
    if args.list_only:
        return cmd_list_only()

    from meum import wizard

    if args.uninstall:
        wizard.unregister_task()
        out("자동 실행 등록을 해제했습니다. (설정과 기록은 남아 있습니다)")
        return 0

    # 처음 실행이거나 --setup 이면 마법사
    if args.setup or (not wizard.is_configured() and args.trigger == "manual"
                      and not args.headless):
        wizard.run_wizard()
        return 0

    # 그냥 두 번 클릭했다면 '할 일 패널'을 연다.
    # 쪽지 정리는 패널이 지켜보다가 조용할 때 알아서 하므로,
    # 선생님이 정리를 '실행'하실 일은 없다. (--collect 로는 여전히 가능)
    if args.trigger == "manual" and not args.collect and not args.headless:
        from meum.widget import show
        show()
        return 0

    # 중복 실행 방지.
    # 하루 두 번(아침·저녁) 돌므로 '오늘 이미 했나'가 아니라
    # '최근 90분 안에 했나'로 거른다 — 보충 실행이 겹치는 것만 막는다.
    if args.trigger in ("daily", "logon") and not args.force:
        st = State()
        recent = st.ran_successfully_within(90)
        st.close()
        if recent:
            out("조금 전에 이미 정리했습니다. 종료합니다.")
            return 0

    # 예약 실행은 창 없이 조용히 정리한다 (auto_mode).
    # 확신도 높은 할 일은 바로 저장되고, 애매한 것은 패널에 '미확정'으로 남아
    # 교사가 패널에서 판단한다. 바로가기로 직접 실행하면 확인 창이 뜬다.
    cfg = config.load()
    headless = args.headless or (
        args.trigger in ("daily", "logon", "watch") and cfg.get("auto_mode", True))

    # 감시가 부른 정리는, 선생님이 자리에 돌아오시면 그 자리에서 멈춘다.
    # (이미 읽은 쪽지는 저장되고, 못 읽은 쪽지는 다음 기회에 그대로 다시 온다)
    should_stop = None
    if args.trigger == "watch":
        from meum.watcher import user_is_back
        should_stop = user_is_back

    return Runner(trigger=args.trigger, headless=headless,
                  should_stop=should_stop).run()


if __name__ == "__main__":
    sys.exit(main())
