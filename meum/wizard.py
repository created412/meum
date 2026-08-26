# -*- coding: utf-8 -*-
"""
메움 설치 마법사 — 새 컴퓨터에서 처음 실행할 때 뜬다.

  1단계  브리티 메신저 확인
  2단계  실행 시간 설정 (아침·저녁 두 번, 각각 수정 가능)
  3단계  완료

캘린더는 프로그램 안에 든 자체 달력을 쓴다.
계정 연결도, 휴대폰 연결도 필요 없다.
"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

from . import APP_NAME, APP_TAGLINE, WINDOW_SETUP, config
from .ui import BG, FG, MUTED, ACCENT, DANGER, WARN_BG, _center, _dpi_aware, _fonts

STEPS = [
    "브리티 메신저 확인",
    "실행 시간 설정",
    "완료",
]

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def app_root() -> Path:
    """실행 파일(또는 소스)이 있는 폴더."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[1]


def is_configured() -> bool:
    """마법사를 이미 마쳤는지."""
    return (Path(config.APP_DIR) / "setup_done").exists()


def mark_configured() -> None:
    config.ensure_dirs()
    (Path(config.APP_DIR) / "setup_done").write_text("ok", encoding="utf-8")


class Wizard:
    def __init__(self):
        _dpi_aware()
        self.cfg = config.load()
        self.step = 0
        self.root = tk.Tk()
        self.root.title(WINDOW_SETUP)
        self.root.configure(bg=BG)
        self.f = _fonts()
        self.f["hero"] = tkfont.Font(family="맑은 고딕", size=20,
                                    weight="bold")
        self._build_frame()
        _center(self.root, 660, 560)

    # ------------------------------------------------------------------
    def _build_frame(self):
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=24, pady=(20, 0))
        self.title_lbl = tk.Label(top, text="", font=self.f["title"], bg=BG, fg=FG)
        self.title_lbl.pack(anchor="w")
        self.step_lbl = tk.Label(top, text="", font=self.f["small"], bg=BG, fg=MUTED)
        self.step_lbl.pack(anchor="w", pady=(4, 0))

        self.bar = ttk.Progressbar(self.root, maximum=len(STEPS) - 1, length=600)
        self.bar.pack(padx=24, pady=(12, 6), fill="x")

        self.btns = tk.Frame(self.root, bg=BG)
        self.btns.pack(side="bottom", fill="x", padx=24, pady=(10, 18))

        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(fill="both", expand=True, padx=24, pady=(8, 0))

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()
        for w in self.btns.winfo_children():
            w.destroy()

    def _head(self, title: str):
        self.title_lbl.configure(text=title)
        self.step_lbl.configure(
            text=f"{self.step + 1}단계 / {len(STEPS)}단계 · {STEPS[self.step]}")
        self.bar["value"] = self.step

    def _p(self, text, color=FG, font="body", pady=(0, 6), wrap=590):
        tk.Label(self.body, text=text, font=self.f[font], bg=BG, fg=color,
                 anchor="w", justify="left", wraplength=wrap).pack(anchor="w", pady=pady)

    def _box(self, text, bg=WARN_BG, fg="#92400e"):
        fr = tk.Frame(self.body, bg=bg)
        fr.pack(fill="x", pady=(6, 10))
        tk.Label(fr, text=text, font=self.f["small"], bg=bg, fg=fg,
                 anchor="w", justify="left", wraplength=570).pack(anchor="w",
                                                                 padx=12, pady=9)

    def _primary(self, text, cmd):
        b = tk.Button(self.btns, text=text, font=self.f["bold"], bg=ACCENT, fg="white",
                      activebackground="#1e40af", activeforeground="white",
                      relief="flat", padx=18, pady=7, command=cmd)
        b.pack(side="right")
        return b

    def _secondary(self, text, cmd, side="right"):
        b = tk.Button(self.btns, text=text, font=self.f["body"], padx=10, command=cmd)
        b.pack(side=side, padx=(8, 0) if side == "right" else (0, 8))
        return b

    # ------------------------------------------------------------------
    def run(self):
        self.show_step()
        self.root.mainloop()

    def show_step(self):
        self._clear()
        [self.s0_brity, self.s1_times, self.s2_done][self.step]()

    def next_step(self):
        self.step = min(self.step + 1, len(STEPS) - 1)
        self.show_step()

    def prev_step(self):
        self.step = max(self.step - 1, 0)
        self.show_step()

    # ---------------- 1단계: 브리티 ----------------
    def s0_brity(self):
        self._head(f"{APP_NAME}을 시작합니다")

        # 이 프로그램이 무엇이고 왜 있는지 — 처음 만나는 화면에서 밝힌다
        hero = tk.Frame(self.body, bg="#0f172a")
        hero.pack(fill="x", pady=(0, 14))
        tk.Label(hero, text=APP_NAME, font=self.f["hero"],
                 bg="#0f172a", fg="#7dd3fc").pack(anchor="w", padx=18, pady=(14, 0))
        tk.Label(hero, text=APP_TAGLINE, font=self.f["body"],
                 bg="#0f172a", fg="#e2e8f0").pack(anchor="w", padx=18, pady=(2, 4))
        tk.Label(hero,
                 text="쪽지는 쌓이고, 마감은 문장 속에 숨어 있습니다.\n"
                      "그 사이로 빠져나간 일들을 대신 찾아 채워 넣습니다.",
                 font=self.f["small"], bg="#0f172a", fg="#94a3b8",
                 justify="left").pack(anchor="w", padx=18, pady=(0, 14))

        self._p("브리티 메신저와 GOE메신저의 쪽지를 읽어 할 일을 정리합니다.\n"
                "브리티가 실행되어 있고 로그인된 상태여야 합니다.")

        result = tk.Label(self.body, text="확인 중…", font=self.f["body"],
                          bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=590)
        result.pack(anchor="w", pady=(14, 0))

        nxt = self._primary("다음", self.next_step)
        nxt.configure(state="disabled")
        self._secondary("다시 확인", lambda: check())

        def check():
            result.configure(text="확인 중…", fg=MUTED)
            self.root.update()

            def work():
                try:
                    from .collector import BrityCollector
                    # 스레드에서는 COM 초기화가 먼저 필요하다
                    with BrityCollector.init_thread():
                        c = BrityCollector(self.cfg, log=lambda s: None)
                        c.attach()
                        name = c.detect_my_name()
                        notes = c.list_notes(scroll_rounds=1)
                        c.restore()
                    msg = (f"연결되었습니다.\n"
                           f"  로그인 사용자: {name or '(확인 못함)'}\n"
                           f"  쪽지함에서 {len(notes)}건을 읽었습니다.")
                    self.root.after(0, lambda: (result.configure(text=msg, fg="#166534"),
                                                nxt.configure(state="normal")))
                    if name:
                        self.cfg = config.update(my_name=name)
                except Exception as e:
                    m = f"연결하지 못했습니다.\n\n{e}"
                    self.root.after(0, lambda: result.configure(text=m, fg=DANGER))

            threading.Thread(target=work, daemon=True).start()

        check()

    # ---------------- 2단계: 실행 시간 ----------------
    def s1_times(self):
        self._head("자동 점검 시각을 직접 정해 주세요")
        self._p("하루 두 번, 정한 시각에 창 없이 조용히 새 쪽지를 정리해\n"
                "바탕화면 패널에 반영합니다. 시각은 선생님이 직접 입력합니다.")

        # 아직 직접 입력한 적이 없으면 빈칸으로 시작한다.
        # 기본값을 채워 두면 그냥 넘어가 버려서 '자기 시각'이 되지 않는다.
        confirmed = bool(self.cfg.get("times_confirmed"))
        v1 = self.cfg.get("run_time", "") if confirmed else ""
        v2 = self.cfg.get("run_time_lunch", "") if confirmed else ""

        grid = tk.Frame(self.body, bg=BG)
        grid.pack(anchor="w", pady=(12, 4))

        tk.Label(grid, text="1차 점검", font=self.f["body"], bg=BG, fg=FG)\
            .grid(row=0, column=0, sticky="w", pady=4)
        self.t1_var = tk.StringVar(value=v1)
        e1 = tk.Entry(grid, textvariable=self.t1_var, font=self.f["body"], width=8)
        e1.grid(row=0, column=1, padx=(12, 0))
        tk.Label(grid, text="예: 08:40  (출근 직후 권장)", font=self.f["small"],
                 bg=BG, fg=MUTED).grid(row=0, column=2, padx=(12, 0), sticky="w")

        tk.Label(grid, text="2차 점검", font=self.f["body"], bg=BG, fg=FG)\
            .grid(row=1, column=0, sticky="w", pady=4)
        self.t2_var = tk.StringVar(value=v2)
        tk.Entry(grid, textvariable=self.t2_var, font=self.f["body"], width=8)\
            .grid(row=1, column=1, padx=(12, 0))
        tk.Label(grid, text="예: 12:40 또는 15:30  (편한 시각으로)",
                 font=self.f["small"],
                 bg=BG, fg=MUTED).grid(row=1, column=2, padx=(12, 0), sticky="w")

        self._box(
            "창은 뜨지 않습니다. 확실한 할 일은 바로 저장되고,\n"
            "애매한 것은 패널에 '미확정'으로 표시되어 거기서 판단하시면 됩니다.\n"
            "그 시각에 컴퓨터가 꺼져 있었다면, 켠 뒤 자동으로 보충 실행됩니다.")

        status = tk.Label(self.body, text="", font=self.f["body"], bg=BG, fg=MUTED,
                          anchor="w", justify="left", wraplength=590)
        status.pack(anchor="w", pady=(6, 0))
        e1.focus_set()

        self._allow_skip = False

        def save_and_next():
            # '다음'이 곧 등록이다.
            # 예전엔 '지금 등록' 단추가 따로 있어서, 시각만 적고 '다음'을 누르면
            # 입력이 조용히 버려졌다. 그 함정을 없앤다.
            t1 = self.t1_var.get().strip()
            t2 = self.t2_var.get().strip()
            if not t1 or not t2:
                status.configure(text="두 시각을 모두 입력해 주세요. (예: 08:40)",
                                 fg=DANGER)
                return
            for t in (t1, t2):
                if not TIME_RE.match(t):
                    status.configure(text=f"'{t}' 는 시각이 아닙니다. "
                                          "HH:MM 형식으로 넣어 주세요 (예: 08:40)",
                                     fg=DANGER)
                    return
            self.cfg = config.update(run_time=t1, run_time_lunch=t2,
                                     times_confirmed=True)
            status.configure(text="등록 중…", fg=MUTED)
            self.root.update()
            ok, msg = register_task(t1, t2)
            if ok:
                status.configure(text=msg, fg="#166534")
                self.root.after(1200, self.next_step)
            else:
                if self._allow_skip:
                    self.next_step()
                    return
                self._allow_skip = True
                status.configure(
                    text=msg + "\n\n한 번 더 '다음'을 누르면 등록 없이 넘어갑니다. "
                               "(나중에 --setup 으로 다시 시도할 수 있습니다)",
                    fg=DANGER)

        self._primary("이 시각으로 등록하고 다음", save_and_next)
        self._secondary("이전", self.prev_step, side="left")

    # ---------------- 3단계: 완료 ----------------
    def s2_done(self):
        self._head("준비가 끝났습니다")
        t1 = self.cfg.get("run_time", "08:40")
        t2 = self.cfg.get("run_time_lunch", "12:40")

        self._p(f"자동 정리 : 매일 {t1} · {t2}, 창 없이 조용히")
        self._p("일정 확인 : 바탕화면 오른쪽 할 일 패널과 안에 든 달력")
        self._p("")
        self._p("이렇게 돌아갑니다.", font="bold")
        self._box(
            "1. 아침·저녁 정해진 시각에 새 쪽지를 조용히 읽어 정리합니다\n"
            "2. 확실한 할 일은 바로 패널과 달력에 들어갑니다\n"
            "3. 애매한 것은 '미확정' 표시로 올라오니 패널에서 판단하세요\n"
            "4. 끝낸 일은 네모(☐)를 눌러 지우고, 두 번 누르면 원래 쪽지가 열립니다\n"
            f"5. 바탕화면 '{APP_NAME} - 쪽지 정리' 로 직접 실행하면 확인 창이 뜹니다",
            bg="#f8fafc", fg=FG)

        self._p("계정 연결도, 휴대폰 연결도 필요 없습니다. "
                "이 컴퓨터 안에서만 동작합니다.", color=MUTED, font="small")

        def finish(run_now: bool):
            mark_configured()
            self.root.destroy()
            if run_now:
                from .app import Runner
                Runner(trigger="manual").run()

        self._primary("지금 정리 실행", lambda: finish(True))
        self._secondary("나중에", lambda: finish(False))
        self._secondary("이전", self.prev_step, side="left")


# --------------------------------------------------------------------------
def register_task(run_time: str = "08:40", lunch_time: str = "12:40") -> tuple:
    """
    작업 스케줄러에 등록. 트리거 두 개(아침·저녁)를 한 작업에 단다.
    (성공여부, 메시지) 반환.

    · StartWhenAvailable : 그 시각에 PC 가 꺼져 있었으면 켠 뒤 보충 실행
    · schtasks 명령줄로는 이 옵션을 못 켜고, 로그온 트리거는 관리자 권한을
      요구해 실패하므로 PowerShell 로 등록한다 (실측 확인)
    """
    exe = sys.executable
    if getattr(sys, "frozen", False):
        cmd_main = f'"{exe}" --trigger daily'
    else:
        runpy = app_root() / "run.py"
        pyw = Path(exe).with_name("pythonw.exe")
        py = str(pyw if pyw.exists() else exe)
        cmd_main = f'"{py}" "{runpy}" --trigger daily'

    exe_path, exe_args = _split_cmd(cmd_main)
    ps = f"""
$ErrorActionPreference = 'Stop'
try {{ Unregister-ScheduledTask -TaskName 'DailyBrief' -TaskPath '\\메움\\' -Confirm:$false }} catch {{}}
try {{ Unregister-ScheduledTask -TaskName 'LogonCatchUp' -TaskPath '\\메움\\' -Confirm:$false }} catch {{}}
$action = New-ScheduledTaskAction -Execute {_ps_quote(exe_path)} -Argument {_ps_quote(exe_args)} -WorkingDirectory {_ps_quote(str(app_root()))}
$t1 = New-ScheduledTaskTrigger -Daily -At '{run_time}'
$t2 = New-ScheduledTaskTrigger -Daily -At '{lunch_time}'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
Register-ScheduledTask -TaskName 'DailyBrief' -TaskPath '\\메움\\' -Action $action `
    -Trigger $t1,$t2 -Settings $settings -Principal $principal `
    -Description '메움 — 브리티·GOE 쪽지에서 놓친 업무를 메워드립니다.' | Out-Null
Write-Output 'OK'
"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, errors="ignore", timeout=90)
        if "OK" in (r.stdout or ""):
            wok = register_widget_autostart()
            sok = create_desktop_shortcuts()
            extra = ""
            if wok:
                extra += "\n로그인하면 바탕화면 패널도 저절로 뜹니다."
            if sok:
                extra += "\n바탕화면에 바로가기를 만들어 두었습니다."
            return True, (f"등록되었습니다. 매일 {run_time} · {lunch_time} 두 번 "
                          f"자동 실행됩니다.\n꺼져 있었다면 켠 뒤 보충 실행됩니다.{extra}")
        err = (r.stderr or r.stdout or "").strip()
        # PowerShell 이 막히면 기본 방식으로 아침 것만이라도
        r2 = subprocess.run(
            ["schtasks", "/Create", "/TN", "메움\\DailyBrief",
             "/TR", cmd_main, "/SC", "DAILY", "/ST", run_time, "/F"],
            capture_output=True, text=True, errors="ignore")
        if r2.returncode == 0:
            return True, (f"등록되었습니다. 매일 {run_time}에 자동 실행됩니다.\n"
                          "(저녁 실행과 보충 실행은 이 컴퓨터에서 등록되지 않았습니다)")
        return False, f"등록하지 못했습니다.\n{err[:200]}"
    except Exception as e:
        return False, f"등록 실패: {e}"


def create_desktop_shortcuts() -> bool:
    """
    바탕화면에 바로가기 두 개를 만든다.

    이 프로그램은 exe 옆의 _internal 폴더와 한 몸이라, exe 만 바탕화면에
    복사하면 'Failed to load Python DLL' 로 죽는다 (실제 발생).
    사람들은 당연히 바탕화면에서 실행하고 싶어 하므로, 파일 복사 대신
    바로가기를 처음부터 만들어 둔다.
    """
    try:
        import win32com.client
        if getattr(sys, "frozen", False):
            exe = sys.executable
        else:
            exe = str(Path(sys.executable).with_name("pythonw.exe"))
        wd = str(app_root())
        desktop = Path.home() / "Desktop"
        if not desktop.exists():
            desktop = Path.home() / "바탕 화면"
        if not desktop.exists():
            return False
        sh = win32com.client.Dispatch("WScript.Shell")

        args_main = "" if getattr(sys, "frozen", False) else f'"{app_root() / "run.py"}"'
        args_widget = ("--widget" if getattr(sys, "frozen", False)
                       else f'"{app_root() / "run.py"}" --widget')

        for name, args, desc in (
                (f"{APP_NAME} - 쪽지 정리", args_main,
                 "브리티·GOE 쪽지를 지금 정리합니다"),
                (f"{APP_NAME} - 할 일 패널", args_widget,
                 "바탕화면 할 일 패널을 엽니다")):
            lnk = sh.CreateShortcut(str(desktop / f"{name}.lnk"))
            lnk.TargetPath = exe
            lnk.Arguments = args
            lnk.WorkingDirectory = wd
            lnk.Description = desc
            lnk.Save()
        return True
    except Exception:
        return False


def register_widget_autostart() -> bool:
    """
    로그인하면 바탕화면 패널이 저절로 뜨게 한다 (HKCU Run 키, 관리자 권한 불필요).

    이게 없으면 이 프로그램은 죽는다: 학교 PC 는 매일 퇴근 때 끄므로,
    아침에 손으로 켜야 보이는 패널은 결국 아무도 안 보게 된다.
    """
    try:
        import winreg
        if getattr(sys, "frozen", False):
            cmd = f'"{sys.executable}" --widget'
        else:
            pyw = Path(sys.executable).with_name("pythonw.exe")
            py = str(pyw if pyw.exists() else sys.executable)
            cmd = f'"{py}" "{app_root() / "run.py"}" --widget'
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, "메움", 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def unregister_widget_autostart() -> None:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, "메움")
        winreg.CloseKey(key)
    except Exception:
        pass


def _split_cmd(cmd: str) -> tuple:
    """'"exe" args…' 를 (exe, args) 로 나눈다."""
    if cmd.startswith('"'):
        end = cmd.index('"', 1)
        return cmd[1:end], cmd[end + 1:].strip()
    parts = cmd.split(" ", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def _ps_quote(s: str) -> str:
    return "'" + (s or "").replace("'", "''") + "'"


def unregister_task() -> None:
    for tn in ("메움\\DailyBrief", "메움\\LogonCatchUp"):
        subprocess.run(["schtasks", "/Delete", "/TN", tn, "/F"],
                       capture_output=True, text=True)
    unregister_widget_autostart()


def run_wizard():
    Wizard().run()
