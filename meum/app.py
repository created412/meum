# -*- coding: utf-8 -*-
"""
전체 흐름 조율.

    09:00 기동
      → 목록 스캔 (창 건드리지 않음)
      → [교사 확인] "정리해서 캘린더에 저장할까요?"
      → 본문 열람 · 할 일 추출
      → [교사 확인] 저장할 일정 선택
      → 캘린더 반영 + 상태 저장
"""
from __future__ import annotations

import logging
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional

from . import WINDOW_PANEL, calendar_sync, config, extractor as extractor_mod, ui
from .collector import (BrityCollector, CollectorError, ListedNote,
                        NotSignedInError)
from .state import State


def setup_logging() -> logging.Logger:
    config.ensure_dirs()
    log_file = Path(config.LOG_DIR) / f"{datetime.now():%Y%m}.log"
    logger = logging.getLogger("meaum")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s"))
    logger.addHandler(fh)
    # 창 모드(--noconsole)로 빌드하면 sys.stdout 이 없다.
    # 그대로 두면 작업 스케줄러 실행 시 로그 출력에서 예외가 난다.
    if sys.stdout is not None:
        try:
            # 콘솔 기본 인코딩(cp949)은 '—' 같은 문자를 못 써서 로깅이 깨진다.
            # 못 쓰는 글자는 대체하도록 해 두어야 실행 자체가 멈추지 않는다.
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(sh)
        except Exception:
            pass
    return logger


class Runner:
    def __init__(self, cfg: Optional[dict] = None, trigger: str = "manual",
                 headless: bool = False,
                 should_stop: Optional[Callable[[], bool]] = None,
                 deep_pages: int = 0):
        self.cfg = cfg or config.load()
        self.trigger = trigger
        self.headless = headless
        # 감시가 부른 정리는 선생님이 자리에 돌아오시면 멈춘다.
        # 못 읽은 쪽지는 '읽음' 표시가 되지 않으므로 다음 기회에 그대로 다시 온다.
        self.should_stop = should_stop
        self.stopped_early = False
        # 지난 쪽지 메우기: 목록을 이만큼 더 내려가며 훑는다(--catchup)
        self.deep_pages = deep_pages
        self.log = setup_logging()
        self.state = State()

    # ------------------------------------------------------------------
    def run(self) -> int:
        window_from = self.state.window_start(self.cfg.get("first_run_lookback_days", 14))
        run_id = self.state.start_run(self.trigger, window_from.isoformat(timespec="seconds"))
        counts = {"collected": 0, "extracted": 0, "synced": 0}
        collector = BrityCollector(self.cfg, log=self.log.info)

        try:
            # --- 1. 목록 스캔 ---
            self.log.info(f"수집 구간 시작점: {window_from:%Y-%m-%d %H:%M}")
            collector.attach()
            notes = collector.list_notes()
            fresh = self._select_fresh(notes, window_from)
            self.log.info(f"신규 대상 {len(fresh)}건 / 전체 목록 {len(notes)}건")

            # --- 2. 교사 확인 (첫 번째 게이트) ---
            mode = "run"
            if not self.headless:
                stale = self._stale_warning()
                mode = ui.ask_start(fresh, window_from, stale_warning=stale)
                if mode == "later":
                    self.log.info("사용자가 '나중에'를 선택했습니다. 아무것도 변경하지 않습니다.")
                    self.state.finish_run(run_id, "skipped", **counts)
                    return 0
            if not fresh and "goe" in (self.cfg.get("sources") or []):
                # 브리티에 새 쪽지가 없어도 GOE 는 따로 확인한다
                goe_only = self._collect_goe()
                if goe_only:
                    counts["extracted"] = len(goe_only)
                    if not self.headless:
                        approved = ui.review_tasks(
                            goe_only,
                            auto_threshold=self.cfg.get("auto_approve_confidence", 0.85))
                        if approved:
                            self._sync(approved, goe_only, reviewed=True)
                    self.state.mark_run_success()
                    self.state.finish_run(run_id, "ok", **counts)
                    self._open_widget()
                    return 0

            if not fresh:
                self.log.info("새 쪽지 없음.")
                self.state.mark_run_success()
                self.state.finish_run(run_id, "ok", **counts)
                if not self.headless:
                    ui.show_summary(["새로 도착한 쪽지가 없습니다.",
                                     "기존 할 일은 그대로 두었습니다."])
                self._open_widget()
                return 0

            use_full = (mode != "preview") and self.cfg.get("collect_mode", "full") == "full"

            # --- 3. 본문 수집 + 추출 ---
            items = self._collect_and_extract(collector, fresh, use_full)
            goe_items = self._collect_goe()
            items = items + goe_items
            counts["collected"] = len(fresh) + len({i["msg_id"] for i in goe_items})
            counts["extracted"] = len(items)

            # --- 4. 교사 확인 (두 번째 게이트) ---
            # 이번에 새로 온 것만 올린다.
            # 지난 것들은 사라지지 않고 바탕화면 패널에 그대로 쌓여 있다.
            offered = items

            if self.headless:
                approved = [i for i in offered
                            if i.get("due_at")
                            and float(i.get("confidence") or 0) >= self.cfg.get(
                                "auto_approve_confidence", 0.85)]
            else:
                approved = ui.review_tasks(
                    offered, auto_threshold=self.cfg.get("auto_approve_confidence", 0.85))
                if approved is None:
                    self.log.info("사용자가 저장을 취소했습니다. "
                                  "추출 결과는 보관되어 다음 실행 때 다시 제시됩니다.")
                    self.state.finish_run(run_id, "skipped", **counts)
                    return 0

            # --- 5. 캘린더 반영 ---
            synced, failed = self._sync(approved, offered,
                                        reviewed=not self.headless)
            counts["synced"] = synced

            # 중간에 멈췄다면 수집 구간을 앞으로 당기지 않는다.
            # 당겨 버리면 아직 열어보지 못한 쪽지가 구간 밖으로 밀려나
            # 영영 정리되지 않는다.
            if self.stopped_early:
                self.log.info("중간에 멈췄으므로 수집 구간을 그대로 둡니다 "
                              "(못 읽은 쪽지는 다음에 다시 정리합니다)")
            else:
                self.state.mark_run_success()
            self.state.finish_run(run_id, "ok", **counts)

            if not self.headless:
                folder = None
                if getattr(self, "batch_ics", None) and self.cfg.get("open_ics_folder", True):
                    pr = getattr(self, "phone_result", None)
                    if not (pr and pr[0]):      # 폰으로 못 보냈을 때만 폴더를 안내
                        folder = str(self.batch_ics.parent)
                ui.show_summary(
                    self._summary_lines(fresh, items, approved, synced, failed),
                    open_folder=folder)
            self.log.info(f"완료: 수집 {counts['collected']} / 추출 {counts['extracted']} / 저장 {synced}")
            self._open_widget()
            return 0

        except NotSignedInError as e:
            # 부팅 직후 09:00 실행에서 흔히 발생한다.
            # last_run_at 을 갱신하지 않으므로 다음 실행에서 그대로 다시 수집한다.
            self.log.warning(f"로그인 필요: {e}")
            self.state.finish_run(run_id, "failed", error="not_signed_in", **counts)
            if not self.headless:
                ui.show_error(
                    f"{e}\n\n로그인하신 뒤 '지금 정리하기'를 실행하시거나, "
                    "내일 아침 9시에 자동으로 다시 시도합니다.\n"
                    "(이번에 못 읽은 쪽지는 다음 실행 때 그대로 다시 정리됩니다)")
            return 4
        except CollectorError as e:
            self.log.error(f"수집 실패: {e}")
            self.state.finish_run(run_id, "failed", error=str(e), **counts)
            if not self.headless:
                ui.show_error(f"{e}\n\n브리티 메신저가 실행 중인지, '쪽지' 화면인지 확인해 주세요.")
            return 2
        except Exception as e:
            self.log.error("예상치 못한 오류\n" + traceback.format_exc())
            self.state.finish_run(run_id, "failed", error=str(e), **counts)
            if not self.headless:
                ui.show_error(f"오류가 발생했습니다.\n\n{e}\n\n로그: {config.LOG_DIR}")
            return 3
        finally:
            collector.restore()
            self.state.close()

    # ------------------------------------------------------------------
    def _open_widget(self) -> None:
        """정리가 끝나면 바탕화면 할 일 패널을 띄운다(이미 떠 있으면 그대로 둔다)."""
        if not self.cfg.get("widget_enabled", True):
            return
        try:
            import win32gui
            found = []
            win32gui.EnumWindows(
                lambda h, _: (found.append(h)
                              if win32gui.IsWindowVisible(h)
                              and win32gui.GetWindowText(h) == WINDOW_PANEL
                              else None, True)[-1], None)
            if found:
                return                      # 이미 떠 있다
        except Exception:
            pass
        try:
            import subprocess
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--widget"]
            else:
                cmd = [sys.executable,
                       str(Path(__file__).resolve().parents[1] / "run.py"), "--widget"]
            # 부모와 완전히 끊어서 띄운다.
            # 파이프를 물려주면 패널이 닫힐 때까지 부모가 끝나지 않아,
            # 작업 스케줄러가 계속 '실행 중'으로 남는다.
            flags = 0
            if hasattr(subprocess, "DETACHED_PROCESS"):
                flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(cmd, close_fds=True, creationflags=flags,
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception as e:
            self.log.warning(f"할 일 패널을 띄우지 못했습니다: {e}")

    # ------------------------------------------------------------------
    def _select_fresh(self, notes: List[ListedNote], window_from: datetime) -> List[ListedNote]:
        known = self.state.known_list_keys()
        out = []
        for n in notes:
            if n.list_key in known:
                continue
            if n.approx_dt and n.approx_dt.date() < (window_from - timedelta(days=1)).date():
                continue
            out.append(n)
        out.sort(key=lambda x: x.approx_dt or datetime.min)
        return out

    def _carry_over(self, exclude: set) -> List[dict]:
        """지난 실행에서 결정하지 않은 항목을 다시 올린다."""
        rows = []
        for r in self.state.pending_tasks():
            if r["task_id"] in exclude:
                continue          # 이번 실행에서 방금 추출한 건은 제외
            d = dict(r)
            d["_carried"] = True
            rows.append(d)
        if rows:
            self.log.info(f"지난 실행에서 남은 승인 대기 {len(rows)}건을 함께 제시합니다.")
        return rows

    def _stale_warning(self) -> Optional[str]:
        days = self.state.days_since_last_success()
        if days is None:
            return "처음 실행입니다. 최근 쪽지를 소급해서 정리합니다."
        if days >= 3:
            return f"자동 정리가 {days}일간 실행되지 않았습니다. 그동안의 쪽지를 함께 정리합니다."
        return None

    # ------------------------------------------------------------------
    def _collect_and_extract(self, collector: BrityCollector,
                             fresh: List[ListedNote], use_full: bool) -> List[dict]:
        ex = extractor_mod.build(self.cfg)
        prog = None if self.headless else ui.Progress(len(fresh))
        items: List[dict] = []
        limit = int(self.cfg.get("max_open_per_run", 30))

        try:
            for i, note in enumerate(fresh, 1):
                label = note.preview[:34] + ("…" if len(note.preview) > 34 else "")
                if prog:
                    prog.step(i - 1, f"({i}/{len(fresh)}) {label}")

                if self.should_stop and i > 1 and self.should_stop():
                    self.log.info(f"선생님이 자리에 돌아오셔서 {i - 1}건까지만 정리했습니다. "
                                  "나머지는 다음 기회에 다시 정리합니다.")
                    self.stopped_early = True
                    break

                detail = None
                if use_full and i <= limit:
                    detail = collector.open_and_read(note)

                if detail:
                    subject = detail.subject or note.preview
                    body = detail.body
                    sender = detail.sender or note.sender
                    org = detail.sender_org
                    received = detail.received_at or note.approx_dt or datetime.now()
                    msg_id = detail.msg_id
                    attachments = ", ".join(detail.attachments)
                else:
                    subject = note.preview
                    body = note.preview
                    sender = note.sender
                    org = ""
                    received = note.approx_dt or datetime.now()
                    msg_id = note.list_key
                    attachments = "첨부있음" if note.has_attach else ""

                thread_key = extractor_mod.normalize_thread_key(subject, sender)
                self.state.upsert_message({
                    "source": "brity",
                    "msg_id": msg_id,
                    "list_key": note.list_key,
                    "thread_key": thread_key,
                    "subject": subject[:200],
                    "sender": sender,
                    "sender_org": org,
                    "received_at": received.isoformat(timespec="seconds"),
                    "body_latest": extractor_mod.strip_quotes(body),
                    "body_raw": body,
                    "attachments": attachments,
                    "processed_at": datetime.now().isoformat(timespec="seconds"),
                })

                for t in ex.extract(subject=subject, body=body, sender=sender,
                                    sender_org=org, received_at=received):
                    row = t.to_row(msg_id, thread_key, "pending")
                    # 추출 즉시 보관한다.
                    # 저장하지 않으면 교사가 검토 창을 취소했을 때 결과가 사라지고,
                    # 쪽지는 이미 처리됨으로 기록되어 다시 잡히지 않는다.
                    row["task_id"] = self.state.add_task(row)
                    items.append(row)

                if prog:
                    prog.step(i, f"({i}/{len(fresh)}) {label}")
        finally:
            if prog:
                prog.close()

        return items

    # ------------------------------------------------------------------
    def _collect_goe(self) -> List[dict]:
        """
        GOE메신저에서도 쪽지를 모은다.

        브리티와 달리 목록을 읽을 수 없어, 위에서부터 한 건씩 열어 보다가
        이미 본 쪽지를 만나면 멈춘다. GOE 가 없거나 실패해도
        브리티 수집 결과에는 영향을 주지 않는다.
        """
        if "goe" not in (self.cfg.get("sources") or ["brity"]):
            return []
        try:
            from .goe_collector import GoeCollector, GoeNotRunning
        except Exception as e:
            self.log.warning(f"GOE 수집기를 불러오지 못했습니다: {e}")
            return []

        items: List[dict] = []
        col = GoeCollector(self.cfg, log=self.log.info)
        try:
            col.attach()
            known = self.state.known_source_keys("goe")
            # 지난 것을 메울 때는 줄 수 상한도 함께 풀어 준다.
            # (상한이 25줄이라, 목록을 내려도 세 화면에서 멈춰 버렸다)
            max_rows = int(self.cfg.get("goe_max_rows", 25))
            if self.deep_pages:
                max_rows = max(max_rows, self.deep_pages * 10)
            notes = col.collect(known_keys=known,
                                max_rows=max_rows,
                                should_stop=self.should_stop,
                                deep_pages=self.deep_pages)
            # 훑으면서 본 줄 순서를 남긴다. GOE 목록은 읽을 수 없어서,
            # 나중에 그 쪽지를 다시 띄울 때 어느 줄을 눌러야 하는지
            # 알 수 있는 유일한 단서다 (reopen.py).
            if getattr(col, "last_order", None):
                import json as _json
                self.state.set_meta("goe_rows", _json.dumps(col.last_order))
            ex = extractor_mod.build(self.cfg)

            for n in notes:
                thread_key = extractor_mod.normalize_thread_key(n.subject, n.sender)
                self.state.upsert_message({
                    "source": "goe",
                    "msg_id": n.key,
                    "list_key": n.key,
                    "thread_key": thread_key,
                    "subject": n.subject[:200],
                    "sender": n.sender,
                    "sender_org": "",
                    "received_at": n.when.isoformat(timespec="seconds"),
                    "body_latest": extractor_mod.strip_quotes(n.body),
                    "body_raw": n.body,
                    "attachments": "",
                    "processed_at": datetime.now().isoformat(timespec="seconds"),
                })
                for t in ex.extract(subject=n.subject, body=n.body, sender=n.sender,
                                    sender_org="", received_at=n.when):
                    # 수신일시를 모르는 쪽지는 상대 표현('내일까지')이 어긋날 수 있어
                    # 확신도를 낮춰 교사가 반드시 확인하게 한다
                    if n.received_at is None and t.due_at:
                        t.confidence = round(min(t.confidence, 0.6), 2)
                    row = t.to_row(n.key, thread_key, "pending")
                    row["source"] = "goe"
                    row["task_id"] = self.state.add_task(row)
                    items.append(row)
        except GoeNotRunning as e:
            self.log.info(f"GOE 건너뜀: {e}")
        except Exception as e:
            self.log.warning(f"GOE 수집 실패(브리티 결과는 유지): {e}")
        finally:
            try:
                col.restore()
            except Exception:
                pass
        return items

    # ------------------------------------------------------------------
    def _sync(self, approved: List[dict], offered: Optional[List[dict]] = None,
              reviewed: bool = True):
        # 검토 창에서 제시했는데 고르지 않은 항목만 '무시'로 확정한다.
        # 교사가 실제로 보고 판단했을 때에만 해당한다.
        #
        # 자동 실행(headless)에서는 화면을 보여준 적이 없으므로 무시로 바꾸면 안 된다.
        # 그대로 'pending' 으로 두어야 바탕화면 패널에 '승인 대기'로 남고
        # 다음 실행 때 다시 제시된다.
        # 예전에는 검토 창에서 고르지 않은 항목을 '무시'로 확정했다.
        # 그러면 교사가 아직 처리하지 못한 일이 다음 날 사라져 버린다.
        # 이제는 아무것도 자동으로 지우지 않는다.
        # 목록에서 빠지는 것은 교사가 패널에서 직접 '완료'로 체크한 것뿐이다.
        _ = (offered, reviewed)   # 시그니처 유지용

        if not approved:
            return 0, []
        try:
            backend = calendar_sync.build(self.cfg, interactive=not self.headless)
        except Exception as e:
            self.log.error(f"캘린더 백엔드 초기화 실패: {e}")
            if not self.headless:
                ui.show_error(f"캘린더 연결에 실패했습니다.\n\n{e}")
            return 0, [("(전체)", str(e))]

        synced, failed = 0, []
        for item in approved:
            row = dict(item)
            row["status"] = "approved"
            task_id = row.get("task_id")

            if task_id:
                self.state.update_task(task_id, title=row["title"], due_at=row["due_at"],
                                       due_kind=row["due_kind"], detail=row["detail"],
                                       status="approved")
            else:
                task_id = self.state.add_task(row)

            task = self.state.con.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            link = self.state.get_link(task_id)
            try:
                # 백엔드는 event_id 문자열을 돌려준다.
                # (여러 곳에 동시 저장하므로 provider 는 백엔드가 정한다)
                event_id = backend.upsert(task, link)
                self.state.link_event(task_id, backend.provider, event_id,
                                      task["due_at"])
                synced += 1
            except Exception as e:
                self.log.error(f"캘린더 등록 실패 ({task['title'][:30]}): {e}")
                failed.append((task["title"], str(e)))

        # 삼성 캘린더 가져오기용 묶음 파일 생성
        try:
            self.batch_ics = backend.finish()
        except Exception:
            self.batch_ics = None
        for msg in getattr(backend, "errors", []):
            self.log.warning(f"캘린더: {msg}")
        self.backend_label = getattr(backend, "label", "")

        # USB 로 연결된 폰이 있으면 파일을 넣어준다 (없으면 조용히 건너뜀)
        self.phone_result = None
        if self.batch_ics and self.cfg.get("send_to_phone", True):
            try:
                from . import phone
                ok, msg = phone.send_file(
                    self.batch_ics, self.cfg.get("phone_device_name") or None)
                self.phone_result = (ok, msg)
                self.log.info(f"휴대폰 전송: {'성공' if ok else '건너뜀'} — {msg}")
            except Exception as e:
                self.phone_result = (False, str(e))
                self.log.warning(f"휴대폰 전송 실패: {e}")

        return synced, failed

    # ------------------------------------------------------------------
    def _summary_lines(self, fresh, items, approved, synced, failed) -> List[str]:
        where = getattr(self, "backend_label", "") or "캘린더"
        lines = [
            f"쪽지 {len(fresh)}건을 확인했습니다.",
            f"할 일 {len(items)}건을 찾았고, {len(approved)}건을 선택하셨습니다.",
            f"{where}에 {synced}건 저장 완료.",
        ]
        lines.append("")
        lines.append("바탕화면 오른쪽 할 일 패널과 달력에서 확인하실 수 있습니다.")
        if "google" in (self.cfg.get("calendar_backends") or []):
            lines.append("(구글 캘린더에도 함께 들어갑니다)")
        if failed:
            lines.append("")
            lines.append(f"실패 {len(failed)}건:")
            for t, e in failed[:5]:
                lines.append(f"  · {t[:40]} — {e[:60]}")
        return lines
