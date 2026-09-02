# 빌드 검증과 코드 서명

## 왜

메움은 개인 제작 프로그램이라 코드 서명이 없어, 백신(V3 등)이
'평판 없는 파일'로 보고 실행할 때마다 확인 창을 띄웁니다.
이를 근본적으로 없애기 위해 두 가지를 합니다.

## 1. 재현 가능한 빌드 (되어 있음)

`v*` 태그를 밀면 GitHub Actions 가 이 소스만으로 설치본을 빌드합니다
(`.github/workflows/build.yml`). 누구나 배포본과 대조해
"배포된 실행 파일 = 이 소스" 를 검증할 수 있습니다.

로컬 빌드: `pip install -r requirements.txt pyinstaller` 후 `python build.py`

## 2. SignPath Foundation 무료 OSS 코드 서명 (신청 중)

[SignPath Foundation](https://signpath.org) 은 공개 소스 프로젝트에
무료 코드 서명을 제공합니다. 승인되면 CI 산출물에 서명이 붙어
모든 백신·SmartScreen 경고가 사라집니다.

- 라이선스: MIT ✓
- 공개 저장소: github.com/created412/meum ✓
- CI 빌드: GitHub Actions ✓
- 유지관리자: 이재영 (histo5731@gmail.com)
