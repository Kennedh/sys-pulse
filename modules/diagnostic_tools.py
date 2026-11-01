import base64
import json
import os
import platform
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from modules.powershell import powershell_environment


LATENCYMON_PAGE = "https://www.resplendence.com/downloads"
LATENCYMON_INSTALLER = "https://www.resplendence.com/download/LatencyMon.exe"
MANUFACTURERS = {
    "NVIDIA": "https://www.nvidia.com/en-us/drivers/",
    "AMD": "https://www.amd.com/en/support/download/drivers.html",
    "Intel": "https://www.intel.com/content/www/us/en/support/detect.html",
}


def find_latencymon():
    if platform.system() != "Windows":
        return None
    folders = [Path(os.environ[key]) / "LatencyMon" for key in ("ProgramFiles", "ProgramFiles(x86)") if os.environ.get(key)]
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", 0, winreg.KEY_READ | view) as root:
                        for index in range(winreg.QueryInfoKey(root)[0]):
                            try:
                                with winreg.OpenKey(root, winreg.EnumKey(root, index)) as item:
                                    name = winreg.QueryValueEx(item, "DisplayName")[0]
                                    if "latencymon" in str(name).lower():
                                        folders.append(Path(winreg.QueryValueEx(item, "InstallLocation")[0]))
                            except OSError:
                                continue
                except OSError:
                    continue
    except ImportError:
        pass
    return next((str(folder / name) for folder in folders for name in ("LatMon.exe", "LatencyMon.exe")
                 if (folder / name).is_file()), None)


def run_powershell(script, cancelled=lambda: False, timeout=120, environment=None):
    import time
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    with subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment or powershell_environment(),
            creationflags=0x08000000 if os.name == "nt" else 0) as process:
        started = time.monotonic()
        while True:
            if cancelled() or time.monotonic() - started > timeout:
                process.kill()
                process.communicate()
                raise RuntimeError("Consulta cancelada." if cancelled() else "O Windows não concluiu a consulta no prazo.")
            try:
                output, error = process.communicate(timeout=.25)
                break
            except subprocess.TimeoutExpired:
                pass
        if process.returncode:
            raise RuntimeError("O Windows não concluiu a consulta. Confira o serviço Windows Update, a conexão e as políticas do sistema.")
        if len(output) > 1024 * 1024:
            raise RuntimeError("A resposta do Windows excedeu o limite de leitura.")
        return json.loads(output.decode("utf-8-sig"))


def query_driver_updates(cancelled=lambda: False):
    if platform.system() != "Windows":
        raise RuntimeError("Consulta de drivers disponível no Windows.")
    script = """
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$session = New-Object -ComObject Microsoft.Update.Session
$session.ClientApplicationID = 'SysPulse'
$result = $session.CreateUpdateSearcher().Search("IsInstalled=0 and Type='Driver' and IsHidden=0")
$items = @()
foreach ($update in $result.Updates) {
    if ($items.Count -ge 100) { break }
    $items += @{
        title = [string]$update.Title
        hardware_id = [string]$update.DriverHardwareID
        manufacturer = [string]$update.DriverManufacturer
        provider = [string]$update.DriverProvider
        model = [string]$update.DriverModel
        date = if ($update.DriverVerDate) { $update.DriverVerDate.ToString('yyyy-MM-dd') } else { $null }
    }
}
@{result_code=[int]$result.ResultCode; total=$result.Updates.Count; updates=@($items)} | ConvertTo-Json -Depth 5 -Compress
"""
    result = run_powershell(script, cancelled)
    if result.get("result_code") not in (2, 3) or not isinstance(result.get("updates"), list):
        raise RuntimeError("O Windows Update retornou uma consulta incompleta. Tente novamente.")
    return result


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname not in ("resplendence.com", "www.resplendence.com"):
            raise ValueError("Redirecionamento do instalador fora do site oficial.")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def download_latencymon(folder, cancelled=lambda: False):
    if platform.system() != "Windows":
        raise RuntimeError("LatencyMon requer Windows.")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "LatencyMon-Setup.exe"
    temporary = folder / "LatencyMon-Setup.part"
    try:
        opener = urllib.request.build_opener(OfficialRedirect())
        request = urllib.request.Request(LATENCYMON_INSTALLER, headers={"User-Agent": "SysPulse"})
        size = 0
        with opener.open(request, timeout=20) as response, temporary.open("wb") as output:
            while True:
                if cancelled():
                    raise RuntimeError("Download cancelado.")
                block = response.read(65536)
                if not block:
                    break
                size += len(block)
                if size > 32 * 1024 * 1024:
                    raise ValueError("O instalador excede o limite de 32 MiB.")
                output.write(block)
        with temporary.open("rb") as source:
            header = source.read(2)
        if size < 65536 or header != b"MZ":
            raise ValueError("O site não retornou um instalador válido.")
        environment = powershell_environment()
        environment["SYSPULSE_INSTALLER"] = str(temporary.resolve())
        signature = run_powershell("""
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$s = Get-AuthenticodeSignature -LiteralPath $env:SYSPULSE_INSTALLER
@{status=[string]$s.Status; publisher=[string]$s.SignerCertificate.Subject} | ConvertTo-Json -Compress
""", cancelled, timeout=30, environment=environment)
        organization = re.search(r"(?:^|,\s*)O=([^,]+)", signature.get("publisher", ""))
        publisher = organization.group(1).strip().casefold() if organization else ""
        allowed = {"softrev labs s.r.l.s.", "resplendence software projects sp.", "resplendence software projects"}
        if signature.get("status") != "Valid" or publisher not in allowed:
            raise ValueError("Não foi possível validar a assinatura do fabricante. Use o site oficial.")
        temporary.replace(target)
        return str(target)
    finally:
        temporary.unlink(missing_ok=True)


def read_latency_report(path):
    path = Path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("O relatório excede 2 MiB.")
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
    if "latencymon" not in text.lower() or "\x00" in text:
        raise ValueError("Selecione o relatório de texto exportado pelo LatencyMon.")
    return text
