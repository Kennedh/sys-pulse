import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import psutil

from modules.wpr_profile import write_profile


TERMINAL = {"completed", "failed", "cancelled"}


def now():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def read_json(path, limit=1024 * 1024):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError("Arquivo de controle excede o limite")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Arquivo de controle inválido")
    return value


def find_tools():
    if os.name != "nt":
        return {"wpr": None, "xperf": None, "windows": False}
    system = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    wpr = system / ("Sysnative" if ctypes.sizeof(ctypes.c_void_p) == 4 else "System32") / "wpr.exe"
    candidates = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "Windows Kits/10/Windows Performance Toolkit/xperf.exe")
    return {"windows": True, "wpr": str(wpr) if wpr.is_file() else None,
            "xperf": next((str(path) for path in candidates if path.is_file()), None)}


def is_admin():
    return os.name == "nt" and bool(ctypes.windll.shell32.IsUserAnAdmin())


def request_admin(arguments):
    if os.name != "nt":
        raise OSError("A captura avançada precisa do Windows.")
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040 | 0x00000400 | 0x00000100
    info.lpVerb, info.lpFile = "runas", sys.executable
    info.lpParameters = subprocess.list2cmdline(arguments)
    info.lpDirectory = str(Path(__file__).resolve().parents[1])
    info.nShow = 0
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code == 1223:
            raise PermissionError("Permissão de administrador recusada. Nenhuma captura foi iniciada.")
        raise OSError(code, "Não foi possível iniciar a captura como administrador")
    if info.hProcess:
        kernel.CloseHandle(info.hProcess)


def wpr_command(executable, instance, *arguments, timeout=120):
    if not re.fullmatch(r"SysPulse_[0-9a-f]{32}", instance):
        raise ValueError("Identificação de captura inválida")
    result = subprocess.run([str(executable), *map(str, arguments), "-instancename", instance],
                            capture_output=True, timeout=timeout, creationflags=0x08000000 if os.name == "nt" else 0)
    encoding = "utf-16" if result.stdout.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
    output = result.stdout.decode(encoding, errors="replace") + result.stderr.decode("utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"WPR retornou {result.returncode}: {output.strip()[:2000]}")
    return output.strip()


class CaptureController:
    def __init__(self):
        self.path = None
        self.launch_error = None
        self._thread = None
        self._closed = threading.Event()
        self.requested_at = 0

    def start(self, folder, seconds=60, mode='detail'):
        if self._thread and self._thread.is_alive():
            raise RuntimeError("A solicitação de administrador ainda está em andamento.")
        if self.path and self.status().get("state") not in TERMINAL:
            raise RuntimeError("Encerre a captura atual antes de iniciar outra.")
        if not find_tools()["wpr"]:
            raise RuntimeError("WPR indisponível. Esta captura requer Windows com wpr.exe.")
        seconds = int(seconds)
        if mode not in ("detail", "circular") or not 15 <= seconds <= (7200 if mode == "circular" else 180):
            raise ValueError("Escolha até 3 min em arquivo ou até 2 h no modo circular.")
        root = Path(folder).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(root).free < 2 * 1024 ** 3:
            raise OSError("Separe pelo menos 2 GiB livres para a captura e a análise.")
        identity = uuid.uuid4().hex
        self.path = root / f"avancado-{datetime.now():%Y%m%d-%H%M%S}-{identity[:8]}"
        self.path.mkdir()
        (self.path / "commands").mkdir()
        self.launch_error = None
        self.requested_at = time.monotonic()
        write_json(self.path / "request.json", {"id": identity, "seconds": seconds, "mode": mode,
                   "parent_pid": os.getpid(), "parent_created": psutil.Process().create_time(), "requested_at": now()})
        arguments = (["--etw-helper", str(self.path), identity] if getattr(sys, "frozen", False) else
                     [str(Path(__file__).resolve().parents[1] / "etw_capture.py"), str(self.path), identity])

        def launch():
            try:
                request_admin(arguments)
            except (OSError, PermissionError) as error:
                self.launch_error = str(error)

        self._thread = threading.Thread(target=launch, name="sys-pulse-uac", daemon=True)
        self._thread.start()
        return self.path

    def status(self):
        if self.launch_error:
            return {"state": "cancelled", "message": self.launch_error}
        if not self.path:
            return {"state": "idle", "message": "Pronto para capturar"}
        try:
            state = read_json(self.path / "status.json")
            if state.get("state") not in TERMINAL and state.get("helper_pid"):
                try:
                    helper = psutil.Process(state["helper_pid"])
                    alive = helper.is_running() and helper.create_time() == state.get("helper_created")
                except psutil.NoSuchProcess:
                    alive = False
                except psutil.AccessDenied:
                    alive = True
                if not alive:
                    instance = state.get("instance", "")
                    return {"state": "failed", "message": "O processo de captura foi interrompido. A sessão WPR pode continuar ativa.",
                            "recovery_command": f"wpr -cancel -instancename {instance}" if re.fullmatch(r"SysPulse_[0-9a-f]{32}", instance) else None}
            return state
        except FileNotFoundError:
            message = "Autorize a captura na janela de administrador do Windows."
            if time.monotonic() - self.requested_at > 120:
                message = "Aguardando resposta do Windows. Confira a janela UAC; use Encerrar para desistir desta solicitação."
            return {"state": "requesting", "message": message}
        except (OSError, ValueError) as error:
            return {"state": "unknown", "message": f"Não foi possível ler o estado da captura: {error}"}

    def stop(self):
        if self.path:
            (self.path / "stop.request").touch()

    def mark(self, note=""):
        if not self.path or self.status().get("state") != "recording":
            return False
        marker = {"id": uuid.uuid4().hex, "timestamp": now(), "monotonic": time.monotonic(), "note": str(note)[:500]}
        write_json(self.path / "commands" / f"{time.time_ns()}-{marker['id']}.json", marker)
        return True

    def close(self):
        self._closed.set()
        self.stop()


def run_capture(folder, identity, run=wpr_command):
    folder = Path(folder).resolve()
    if not re.fullmatch(r"[0-9a-f]{32}", identity):
        raise ValueError("Identificação inválida")
    request = read_json(folder / "request.json")
    mode = request.get("mode", "detail")
    maximum = 7200 if mode == "circular" else 180
    if (mode not in ("detail", "circular") or request.get("id") != identity
            or type(request.get("seconds")) is not int or not 15 <= request["seconds"] <= maximum):
        raise ValueError("Solicitação inválida")
    instance = "SysPulse_" + identity
    state = {"instance": instance, "requested_at": request.get("requested_at"), "updated_at": now()}
    attempted = False
    saved = False
    executable = find_tools()["wpr"]

    def status(name, message, **extra):
        state.update(state=name, message=message, updated_at=now(), **extra)
        write_json(folder / "status.json", state)

    try:
        if not is_admin() or not executable:
            raise RuntimeError("A captura precisa de WPR e permissão de administrador.")
        state.update(helper_pid=os.getpid(), helper_created=psutil.Process().create_time())
        parent = psutil.Process(request["parent_pid"])
        if parent.create_time() != request["parent_created"]:
            raise RuntimeError("O aplicativo que solicitou a captura já foi encerrado.")
        if (folder / "stop.request").exists():
            status("cancelled", "Solicitação encerrada antes de iniciar o WPR.")
            return
        temporary = folder / "wpr-temp"
        temporary.mkdir(exist_ok=True)
        status("starting", "Preparando a gravação do Windows…")
        attempted = True
        if mode == "circular":
            profile = write_profile(folder / "perfil.wprp")
            run(executable, instance, "-start", str(profile) + "!SysPulse.Light")
        else:
            run(executable, instance, "-start", "GeneralProfile.Light", "-filemode", "-recordtempto", temporary)
        start = time.monotonic()
        status("recording", "Reproduza o problema e marque quando perceber o sintoma.", started_at=now(), seconds=request["seconds"])
        reason = "Tempo de captura atingido"
        save_at = None
        while time.monotonic() - start < request["seconds"]:
            if save_at is not None and time.monotonic() >= save_at:
                reason = "Janela do sintoma preservada após a marcação"
                break
            if (folder / "stop.request").exists():
                reason = "Encerrada pelo usuário"
                break
            if not parent.is_running():
                reason = "Aplicativo encerrado; captura salva pelo processo auxiliar"
                break
            if shutil.disk_usage(folder).free < 1024 ** 3:
                reason = "Pouco espaço livre; captura interrompida para salvar os dados"
                break
            if sum(path.stat().st_size for path in temporary.rglob("*.etl") if path.is_file()) > 1024 ** 3:
                reason = "Limite aproximado de 1 GiB de dados temporários atingido"
                break
            for command in sorted((folder / "commands").glob("*.json"))[:10]:
                try:
                    marker = read_json(command, 4096)
                    marker_id = marker.get("id", "")
                    if not re.fullmatch(r"[0-9a-f]{32}", marker_id):
                        raise ValueError("Marcação inválida")
                    run(executable, instance, "-marker", f"SYSPULSE:{marker_id}", timeout=10)
                    marker["wpr_marker"] = True
                    if mode == "circular" and save_at is None:
                        save_at = time.monotonic() + 5
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                    marker = {"id": command.stem, "wpr_marker": False, "error": str(error)}
                marker["acknowledged_at"] = now()
                with (folder / "markers.jsonl").open("a", encoding="utf-8") as output:
                    output.write(json.dumps(marker, ensure_ascii=False) + "\n")
                command.unlink(missing_ok=True)
            time.sleep(.25)
        status("stopping", "Finalizando o ETL; aguarde a gravação do arquivo.", reason=reason)
        try:
            (folder / "wpr-status.txt").write_text(run(executable, instance, "-status"), encoding="utf-8")
        except (RuntimeError, OSError, subprocess.SubprocessError):
            pass
        run(executable, instance, "-stop", folder / "captura.etl", "SysPulse - investigacao de desempenho", "-compress", timeout=180)
        if not (folder / "captura.etl").is_file() or not (folder / "captura.etl").stat().st_size:
            raise RuntimeError("O WPR não produziu um ETL válido.")
        saved = True
        status("completed", "Captura salva. Preparando a análise…", ended_at=now(), etl="captura.etl")
    except Exception as error:
        cleanup_error = None
        if attempted and not saved:
            try:
                run(executable, instance, "-cancel", timeout=30)
            except Exception as cleanup:
                cleanup_error = str(cleanup)
        status("failed", f"Não foi possível concluir a captura: {error}", cleanup_error=cleanup_error,
               recovery_command=f'wpr -cancel -instancename {instance}' if cleanup_error else None)
