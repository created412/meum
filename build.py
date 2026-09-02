# -*- coding: utf-8 -*-
"""
단일 실행 파일(메움.exe) 만들기.

    python build.py

결과: dist/메움/ 폴더 하나.
      이 폴더를 통째로 USB나 다른 PC에 옮기면 Python 없이 바로 실행된다.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
NAME = "메움"

HIDDEN = [
    "uiautomation", "comtypes", "comtypes.stream",
    "win32gui", "win32con", "win32api", "win32process",
    "tkinter", "tkinter.filedialog", "tkinter.messagebox", "tkinter.ttk",
    "sqlite3", "calendar", "winsound",
    "meum.doctor", "meum.watcher",       # 필요할 때만 불러오므로 명시한다
    # Google 캘린더
    "win32com", "win32com.client", "pythoncom",     # 휴대폰 전송(MTP)
    "googleapiclient", "googleapiclient.discovery", "googleapiclient.http",
    "google.oauth2.credentials", "google.auth.transport.requests",
    "google_auth_oauthlib", "google_auth_oauthlib.flow",
    "google_auth_httplib2", "httplib2",
]


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller 가 없습니다.  pip install pyinstaller")
        return 1

    for d in (DIST, BUILD):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    # 파일 속성(버전 정보)을 넣는다.
    #
    # 서명 없는 낯선 exe 는 백신(V3 등)의 평판 검사에 계속 걸린다.
    # 서명을 살 수는 없지만, 제작자·제품명·버전이 담긴 속성이라도 넣으면
    # '정체불명 파일' 취급이 줄어든다. (완전한 해결은 코드 서명뿐이며,
    # 각 PC 에서 V3 예외 등록을 안내하는 것과 함께 쓴다)
    from meum import __version__ as VER
    nums = (VER.split(".") + ["0", "0", "0"])[:3]
    vtuple = ", ".join(nums + ["0"])
    version_file = BUILD / "version_info.txt"
    BUILD.mkdir(parents=True, exist_ok=True)
    version_file.write_text(f'''
VSVersionInfo(
  ffi=FixedFileInfo(filevers=({vtuple}), prodvers=({vtuple})),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '이재영 (양지고등학교)'),
      StringStruct('FileDescription', '메움 - 메신저에서 놓친 업무를 메워드립니다'),
      StringStruct('FileVersion', '{VER}'),
      StringStruct('ProductName', '메움 (Meum)'),
      StringStruct('ProductVersion', '{VER}'),
      StringStruct('LegalCopyright', 'MIT License · github.com/created412/meum'),
      StringStruct('OriginalFilename', '메움.exe')])]),
    VarFileInfo([VarStruct('Translation', [1042, 1200])])
  ]
)
''', encoding="utf-8")

    args = [
        sys.executable, "-m", "PyInstaller",
        "--version-file", str(version_file),
        "--name", NAME,
        "--noconsole",              # 검은 콘솔 창 안 뜨게
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
    ]
    for h in HIDDEN:
        args += ["--hidden-import", h]

    # googleapiclient 는 discovery 캐시 파일이 필요하다
    try:
        import googleapiclient
        pkg = Path(googleapiclient.__file__).parent
        args += ["--collect-data", "googleapiclient"]
        if (pkg / "discovery_cache").exists():
            args += ["--collect-submodules", "googleapiclient.discovery_cache"]
    except Exception:
        pass

    args.append(str(ROOT / "run.py"))

    print("빌드 중… (몇 분 걸립니다)\n")
    r = subprocess.run(args)
    if r.returncode != 0:
        print("\n빌드 실패")
        return r.returncode

    out = DIST / NAME
    # 사용 설명서를 함께 넣는다
    for f in ("README.md", "사용설명서.txt", "PRIVACY.md", "LICENSE"):
        src = ROOT / f
        if src.exists():
            shutil.copy2(src, out / f)

    # 압축을 푼 사람이 가장 먼저 볼 안내. 빌드할 때마다 dist 를 비우므로
    # 손으로 넣어 두면 다음 빌드에서 사라진다 — 그래서 여기서 만든다.
    first = ROOT / "처음이라면.txt"
    if first.exists():
        shutil.copy2(first, out / "★ 처음이라면.txt")

    # 연결이 안 될 때 두 번 클릭으로 진단 보고서를 만드는 배치
    doctor_bat = ROOT / "진단하기.bat"
    if doctor_bat.exists():
        shutil.copy2(doctor_bat, out / "진단하기.bat")

    print(f"\n완료: {out}")
    print(f"실행 파일: {out / (NAME + '.exe')}")
    print("\n이 폴더를 통째로 다른 PC에 옮기면 Python 설치 없이 바로 실행됩니다.")
    print("(Google 인증 파일 client_secret.json 을 이 폴더에 함께 두면")
    print(" 새 PC에서 인증 파일을 다시 만들 필요가 없습니다)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
