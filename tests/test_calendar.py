# -*- coding: utf-8 -*-
"""
캘린더 백엔드 검증.

특히 백엔드 ↔ 호출부의 '반환값 모양'을 고정한다.
(다중 백엔드로 바꾸면서 반환값이 튜플→문자열로 달라졌는데 호출부를 안 고쳐
 .ics 파일은 만들어지는데 저장 건수가 0으로 집계된 적이 있다)
"""
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brity_todo import config                     # noqa: E402
from brity_todo import calendar_sync              # noqa: E402


def make_task(task_id, title, due_at, kind="deadline"):
    return {
        "task_id": task_id, "title": title, "due_at": due_at, "due_kind": kind,
        "requester": "김하늘(○○고등학교)", "category": "제출",
        "detail": "점검사항 확인 후 회신", "warn": "",
    }


def main():
    tmp = Path(tempfile.mkdtemp(prefix="brity_cal_"))
    orig = config.ICS_DIR
    config.ICS_DIR = tmp
    fails = []

    try:
        cfg = dict(config.DEFAULTS)
        cfg["calendar_backends"] = ["ics"]          # 네트워크 없이 검증
        backend = calendar_sync.build(cfg, interactive=False)

        print(f"백엔드: {backend.label}")

        tasks = [
            make_task(1, "수정된 평가계획 제출", "2026-08-19T14:00"),
            make_task(2, "과학명사특강", "2026-08-28T16:00", "event"),
            make_task(3, "종일 행사", "2026-09-01", "event"),
        ]

        ids = []
        for t in tasks:
            r = backend.upsert(t, None)
            ids.append(r)
            print(f"  upsert 반환: {type(r).__name__}  {str(r)[:40]}")
            if not isinstance(r, str):
                fails.append(f"upsert 는 event_id 문자열을 돌려줘야 함 (받은 값: {type(r)})")

        if len(set(ids)) != len(ids):
            fails.append("event_id 가 중복됨")

        # 호출부와 같은 방식으로 써 본다 (회귀 방지의 핵심)
        try:
            event_id = backend.upsert(tasks[0], None)
            provider = backend.provider
            assert isinstance(event_id, str) and isinstance(provider, str)
        except Exception as e:
            fails.append(f"호출부 방식으로 쓸 수 없음: {e}")

        batch = backend.finish()
        print(f"\n묶음 파일: {batch.name if batch else '없음'}")
        if not batch or not batch.exists():
            fails.append("삼성 캘린더용 묶음 파일이 만들어지지 않음")
        else:
            text = batch.read_text(encoding="utf-8")
            n = text.count("BEGIN:VEVENT")
            print(f"  포함된 일정: {n}건")
            if n != 4:
                fails.append(f"묶음 파일에 4건이 있어야 하는데 {n}건")
            for must in ("BEGIN:VCALENDAR", "X-WR-CALNAME", "BEGIN:VALARM",
                         "DTSTART;TZID=Asia/Seoul", "DTSTART;VALUE=DATE"):
                if must not in text:
                    fails.append(f"묶음 파일에 {must} 가 없음")
            if "[마감] 수정된 평가계획 제출" not in text:
                fails.append("마감 항목 제목 접두어가 빠짐")

        # 기본값에서는 일정마다 파일을 따로 만들지 않는다(폴더가 지저분해짐).
        # 폰으로 옮길 묶음 파일 하나만 있으면 된다.
        files = list(tmp.glob("*.ics"))
        print(f"생성된 파일: {len(files)}건 — {[f.name for f in files]}")
        if len(files) != 1:
            fails.append(f"묶음 파일 하나만 있어야 하는데 {len(files)}건")


        # --- 재실행 시 중복 방지 (삼성 캘린더 가져오기의 핵심) ---
        print("\n[재실행] 같은 할 일을 다시 정리했을 때")
        b2 = calendar_sync.build(cfg, interactive=False)
        again = [b2.upsert(t, None) for t in tasks]
        for first, second in zip(ids, again):
            if first != second:
                fails.append(f"같은 할 일인데 UID 가 달라짐: {first} vs {second}")
        print(f"  UID 동일 여부: {'같음 (중복 안 쌓임)' if ids == again else '다름 (중복 위험)'}")

        f2 = b2.finish()
        if f2:
            t1 = batch.read_text(encoding="utf-8")
            t2 = f2.read_text(encoding="utf-8")
            import re as _re
            seq1 = int(_re.search(r"SEQUENCE:(\d+)", t1).group(1))
            seq2 = int(_re.search(r"SEQUENCE:(\d+)", t2).group(1))
            print(f"  SEQUENCE: {seq1} → {seq2}")
            if seq2 < seq1:
                fails.append("SEQUENCE 가 줄어들면 캘린더가 갱신을 무시한다")
            if f2.name == batch.name:
                fails.append("같은 날 두 번 정리했는데 파일을 덮어씀")

        # 설정이 비어 있어도 최소한 .ics 로는 저장되어야 한다
        cfg2 = dict(config.DEFAULTS)
        cfg2["calendar_backends"] = []
        b2 = calendar_sync.build(cfg2, interactive=False)
        if not b2.backends:
            fails.append("백엔드가 하나도 없을 때 .ics 폴백이 없음")
        else:
            print(f"\n폴백 확인: {b2.label}")

    finally:
        config.ICS_DIR = orig
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 54)
    if fails:
        print(f"실패 {len(fails)}건")
        for f in fails:
            print(f"  · {f}")
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
