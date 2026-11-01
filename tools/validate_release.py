import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.version import VERSION


def run(arguments, timeout=45):
    result = subprocess.run([str(item) for item in arguments], cwd=ROOT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stdout.decode("utf-8", "replace")[-4000:])
    return result


def windows(output):
    installer = output / f"SysPulse-{VERSION}-Windows-x64-Setup.exe"
    portable = output / f"SysPulse-{VERSION}-Windows-x64-Portable.zip"
    with zipfile.ZipFile(portable) as archive:
        if archive.testzip():
            raise ValueError("ZIP corrompido.")
        required = {"SysPulse/SysPulse.exe", "SysPulse/LICENSE.txt",
                    "SysPulse/_internal/examples/sessao-demo/dpc-isr-simulado.txt"}
        if not required.issubset(archive.namelist()):
            raise ValueError("ZIP incompleto.")
    run([ROOT / "dist/SysPulse/SysPulse.exe", "--smoke-test"])
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{5385F142-031A-4928-9569-760BA8FC6783}_is1"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            return {"smoke": True, "installer": "preservado: instalação existente"}
    except FileNotFoundError:
        pass
    with tempfile.TemporaryDirectory(prefix="syspulse-installer-") as folder:
        destination = Path(folder) / "Pasta de teste" / "SysPulse"
        log = Path(folder) / "install.log"
        run([installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOICONS",
             f"/DIR={destination}", f"/LOG={log}"], timeout=120)
        try:
            run([destination / "SysPulse.exe", "--smoke-test"])
            if not (destination / "unins000.exe").is_file():
                raise ValueError("Desinstalador ausente.")
        finally:
            uninstaller = destination / "unins000.exe"
            if uninstaller.is_file():
                run([uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=60)
        if (destination / "SysPulse.exe").exists():
            raise ValueError("O executável permaneceu após desinstalar.")
    return {"smoke": True, "installer": True, "uninstaller": True, "custom_folder": True}


def linux(output, architecture):
    installer = output / f"SysPulse-{VERSION}-Linux-{architecture}-Setup.run"
    with tempfile.TemporaryDirectory(prefix="syspulse-installer-") as folder:
        destination = Path(folder) / "Pasta de teste" / "SysPulse"
        run(["sh", installer, "--prefix", destination, "--yes", "--no-launch", "--no-desktop"], timeout=120)
        run([destination / "SysPulse", "--smoke-test"])
        run(["sh", destination / "uninstall.sh", "--yes"])
        if destination.exists():
            raise ValueError("Pasta de instalação permaneceu após remover.")
    return {"smoke": True, "installer": True, "uninstaller": True, "custom_folder": True}


def macos(output, architecture):
    package = output / f"SysPulse-{VERSION}-macOS-{architecture}-Setup.pkg"
    image = output / f"SysPulse-{VERSION}-macOS-{architecture}.dmg"
    run(["pkgutil", "--payload-files", package])
    with tempfile.TemporaryDirectory(prefix="syspulse-installer-") as folder:
        mount = Path(folder) / "volume"
        run(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", mount, image])
        try:
            run([mount / "SysPulse.app/Contents/MacOS/SysPulse", "--smoke-test"])
        finally:
            run(["hdiutil", "detach", mount])
    return {"smoke": True, "dmg": True, "pkg_payload": True}


def main():
    parser = argparse.ArgumentParser()
    parser.parse_args()
    system = platform.system()
    architecture = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    output = ROOT / "dist/releases"
    if system == "Windows":
        result = windows(output)
    elif system == "Linux":
        result = linux(output, architecture)
    else:
        result = macos(output, architecture)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
