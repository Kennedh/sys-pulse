import hashlib
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools/bin"
INNO_URL = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe"
INNO_SHA256 = "a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c"
PRESENTMON_URL = "https://github.com/GameTechDev/PresentMon/releases/download/v2.6.0/PresentMon-2.6.0-x64.exe"
PRESENTMON_SHA256 = "b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af"


def download(url, target, expected):
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        return
    temporary = target.with_suffix(".download")
    size = 0
    with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > 100 * 1024 ** 2:
                raise ValueError("Ferramenta excedeu o limite de download.")
            output.write(block)
    if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
        raise ValueError("SHA-256 diferente da ferramenta validada.")
    temporary.replace(target)


def signature(path):
    literal = str(path).replace("'", "''")
    command = "$s = Get-AuthenticodeSignature -LiteralPath '" + literal + "'; if ($s.Status -ne 'Valid') { exit 1 }"
    shell = shutil.which("pwsh") or "powershell"
    environment = dict(os.environ)
    environment.pop("PSModulePath", None)
    subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", command], check=True, env=environment)


def main():
    if os.name != "nt":
        raise SystemExit("As ferramentas auxiliares desta etapa s?o exclusivas do Windows.")
    TOOLS.mkdir(parents=True, exist_ok=True)
    installer = TOOLS / "innosetup-6.7.4.exe"
    download(INNO_URL, installer, INNO_SHA256)
    signature(installer)
    compiler = TOOLS / "InnoSetup"
    if not (compiler / "ISCC.exe").exists():
        subprocess.run([str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                        "/CURRENTUSER", "/DIR=" + str(compiler)], check=True)
    presentmon = TOOLS / "PresentMon.exe"
    download(PRESENTMON_URL, presentmon, PRESENTMON_SHA256)
    signature(presentmon)
    shutil.copy2(ROOT / "installer/licenses/PresentMon-LICENSE.txt", TOOLS / "PresentMon-LICENSE.txt")
    print("Compilador e PresentMon conferidos.")


if __name__ == "__main__":
    main()
