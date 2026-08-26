# -*- coding: utf-8 -*-
"""
USB 로 연결된 휴대폰에 .ics 파일을 넣어준다.

왜 필요한가
-----------
삼성 캘린더에는 외부 프로그램이 일정을 직접 넣을 수 있는 공개 API 가 없다.
방법은 .ics 파일을 가져오는 것뿐인데, 그 파일을 폰으로 옮기는 일이 번거롭다.
폰을 USB 로 꽂아두면 이 모듈이 자동으로 넣어주므로,
선생님은 폰에서 파일을 한 번 누르기만 하면 된다.

원리
----
안드로이드 폰은 USB 로 연결하면 MTP 장치로 잡힌다.
Windows 탐색기가 이를 폴더처럼 보여주므로, 탐색기(Shell) COM 을 통해
'내 파일 > Download' 폴더에 복사한다.

폰이 없거나 '파일 전송' 모드가 아니면 조용히 건너뛴다. 실패해도 정리 작업 자체는
영향받지 않는다.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional, Tuple

# 폰 안에서 파일을 넣을 후보 폴더 (앞쪽 우선)
TARGET_DIRS = ["Download", "Downloads", "다운로드", "Documents", "문서"]

# 휴대폰으로 볼 만한 장치 이름 힌트
PHONE_HINTS = ("galaxy", "sm-", "samsung", "갤럭시", "phone", "android")


def _shell():
    import win32com.client
    return win32com.client.Dispatch("Shell.Application")


def _this_pc(shell):
    # 17 = ssfDRIVES ('내 PC')
    return shell.NameSpace(17)


def list_devices() -> List[str]:
    """'내 PC' 에 붙어 있는 휴대폰 후보 이름."""
    out = []
    try:
        pc = _this_pc(_shell())
        if pc is None:
            return out
        for item in pc.Items():
            try:
                name = str(item.Name)
            except Exception:
                continue
            # 드라이브 문자가 있는 것은 일반 디스크
            if item.IsFileSystem:
                continue
            out.append(name)
    except Exception:
        pass
    return out


def _find_phone(shell, prefer: Optional[str] = None):
    pc = _this_pc(shell)
    if pc is None:
        return None, ""
    candidates = []
    for item in pc.Items():
        try:
            if item.IsFileSystem:
                continue
            name = str(item.Name)
        except Exception:
            continue
        candidates.append((name, item))

    if prefer:
        for name, item in candidates:
            if prefer.lower() in name.lower():
                return item, name
    for name, item in candidates:
        if any(h in name.lower() for h in PHONE_HINTS):
            return item, name
    # 이름으로 못 고르면, 내부 저장공간을 가진 첫 장치
    for name, item in candidates:
        try:
            if item.GetFolder is not None and len(list(item.GetFolder.Items())) > 0:
                return item, name
        except Exception:
            continue
    return None, ""


def _find_target_folder(device_item):
    """장치 안에서 '내부 저장공간 > Download' 같은 폴더를 찾는다."""
    try:
        storages = device_item.GetFolder
    except Exception:
        return None, ""
    if storages is None:
        return None, ""

    for storage in storages.Items():           # 내부 저장공간 / SD 카드
        try:
            folder = storage.GetFolder
            if folder is None:
                continue
        except Exception:
            continue
        names = {}
        for sub in folder.Items():
            try:
                names[str(sub.Name)] = sub
            except Exception:
                continue
        for want in TARGET_DIRS:
            for nm, sub in names.items():
                if nm.lower() == want.lower():
                    try:
                        return sub.GetFolder, f"{storage.Name}/{nm}"
                    except Exception:
                        continue
        # Download 가 없으면 저장공간 최상위에 넣는다
        return folder, str(storage.Name)
    return None, ""


def send_file(path: Path, prefer_device: Optional[str] = None,
              timeout: float = 30.0) -> Tuple[bool, str]:
    """
    파일을 폰으로 복사한다.
    반환: (성공여부, 메시지)
    """
    path = Path(path)
    if not path.exists():
        return False, "보낼 파일이 없습니다."

    try:
        shell = _shell()
    except Exception as e:
        return False, f"Windows 탐색기 기능을 쓸 수 없습니다: {e}"

    device, dev_name = _find_phone(shell, prefer_device)
    if device is None:
        return False, "USB로 연결된 휴대폰을 찾지 못했습니다."

    folder, where = _find_target_folder(device)
    if folder is None:
        return False, (f"'{dev_name}' 은(는) 찾았지만 내부 저장공간을 열 수 없습니다.\n"
                       "폰 화면에서 USB 연결 방식을 '파일 전송'으로 바꿔 주세요.")

    try:
        before = {str(i.Name) for i in folder.Items()}
    except Exception:
        before = set()

    try:
        # 4 = 진행 대화상자 숨김, 16 = 덮어쓰기 확인 자동 '예'
        folder.CopyHere(str(path), 4 | 16)
    except Exception as e:
        return False, f"복사에 실패했습니다: {e}"

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.6)
        try:
            now = {str(i.Name) for i in folder.Items()}
        except Exception:
            break
        if path.name in now or (now - before):
            return True, f"{dev_name} 의 {where} 폴더로 보냈습니다."
    return False, ("복사를 시작했지만 확인하지 못했습니다. "
                   "폰의 다운로드 폴더를 확인해 주세요.")


def is_phone_connected() -> bool:
    try:
        shell = _shell()
        device, _ = _find_phone(shell)
        return device is not None
    except Exception:
        return False
