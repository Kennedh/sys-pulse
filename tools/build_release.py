import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.version import VERSION


def run(arguments):
    subprocess.run([str(argument) for argument in arguments], cwd=ROOT, check=True)


def compiler():
    candidates = [os.environ.get("ISCC"), shutil.which("ISCC"),
                  ROOT / "tools/bin/InnoSetup/ISCC.exe"]
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", "")):
        for edition in ("6", "7"):
            candidates.append(Path(base) / f"Inno Setup {edition}/ISCC.exe")
    return next((str(path) for path in candidates if path and Path(path).is_file()), None)


def freeze(system):
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir",
            "--name", "SysPulse", "--add-data", "assets/syspulse.svg:assets",
            "--add-data", "examples/sessao-demo:examples/sessao-demo"]
    if system == "Windows":
        args += ["--icon", "assets/syspulse.ico",
                 "--add-data", "modules/inspect_windows.ps1:modules"]
        if (ROOT / "tools/bin/PresentMon.exe").is_file():
            if not (ROOT / "tools/bin/PresentMon-LICENSE.txt").is_file():
                raise ValueError("Inclua a licença do PresentMon antes de distribuir.")
            for name in ("PresentMon.exe", "PresentMon-LICENSE.txt"):
                args += ["--add-data", f"tools/bin/{name}:tools/bin"]
    elif system == "Darwin":
        args += ["--osx-bundle-identifier", "com.kennedh.syspulse"]
    args.append("main.py")
    run(args)


def readme(folder):
    shutil.copy2(ROOT / "LICENSE", folder / "LICENSE.txt")
    (folder / "LEIA-ME.txt").write_text(
        "SYS-PULSE " + VERSION + "\n\n"
        "Abra o aplicativo e siga a configuração inicial. Python não precisa estar instalado.\n"
        "Comece em Investigar com a captura leve. Marque o sintoma e encerre para analisar.\n"
        "A análise integrada funciona sem conta, chave ou modelo.\n"
        "A IA local é opcional: o Ollama e os modelos são baixados separadamente em Configurações.\n"
        "A nuvem anônima funciona sem login ou chave, com fila e disponibilidade comunitária.\n"
        "A IA só trabalha depois da captura. Downloads bloqueiam novas medições.\n"
        "Fechar pode minimizar para a bandeja; use Sair para encerrar.\n"
        "Guia e testes: https://github.com/Kennedh/sys-pulse#readme\n"
        "Downloads: https://github.com/Kennedh/sys-pulse/releases\n", encoding="utf-8")


def windows(output):
    source = ROOT / "dist/SysPulse"
    readme(source)
    archive = output / f"SysPulse-{VERSION}-Windows-x64-Portable.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as target:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                if source.resolve() not in path.resolve().parents:
                    raise ValueError("Arquivo fora da distribuição.")
                target.write(path, str(path.relative_to(source.parent)))
    executable = compiler()
    if not executable:
        raise RuntimeError("Instale Inno Setup 6.6 ou superior, ou configure ISCC.")
    run([executable, "/Qp", f"/DAppVersion={VERSION}", f"/DProjectRoot={ROOT}", ROOT / "installer/windows.iss"])


def linux(output, architecture):
    source = ROOT / "dist/SysPulse"
    readme(source)
    shutil.copy2(ROOT / "installer/linux-uninstall.sh", source / "uninstall.sh")
    (source / "uninstall.sh").chmod(0o755)
    archive = output / f"SysPulse-{VERSION}-Linux-{architecture}-Portable.tar.gz"
    with tarfile.open(archive, "w:gz", compresslevel=6) as target:
        target.add(source, arcname="SysPulse")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    header = (ROOT / "installer/linux-header.sh").read_text(encoding="utf-8")
    header = header.replace("@VERSION@", VERSION).replace("@SHA256@", digest)
    installer = output / f"SysPulse-{VERSION}-Linux-{architecture}-Setup.run"
    with installer.open("wb") as target, archive.open("rb") as payload:
        target.write(header.encode("utf-8"))
        shutil.copyfileobj(payload, target, length=1024 * 1024)
    installer.chmod(0o755)


def macos(output, architecture):
    app = ROOT / "dist/SysPulse.app"
    resources = app / "Contents/Resources"
    resources.mkdir(parents=True, exist_ok=True)
    readme(resources)
    import plistlib
    info = app / "Contents/Info.plist"
    data = plistlib.loads(info.read_bytes())
    data.update(CFBundleShortVersionString=VERSION, CFBundleVersion=VERSION, LSMinimumSystemVersion="13.0")
    info.write_bytes(plistlib.dumps(data))
    run(["codesign", "--force", "--deep", "--sign", "-", app])
    staging = ROOT / "build" / ("macos-package-" + architecture)
    staging.mkdir(parents=True, exist_ok=True)
    shutil.copytree(app, staging / app.name, dirs_exist_ok=True, symlinks=True)
    package = output / f"SysPulse-{VERSION}-macOS-{architecture}-Setup.pkg"
    run(["pkgbuild", "--root", staging, "--install-location", "/Applications",
         "--identifier", "com.kennedh.syspulse", "--version", VERSION,
         "--ownership", "recommended", package])
    image = output / f"SysPulse-{VERSION}-macOS-{architecture}.dmg"
    if image.exists():
        image.unlink()
    link = staging / "Applications"
    if not link.exists():
        link.symlink_to("/Applications")
    run(["hdiutil", "create", "-volname", "SysPulse " + VERSION, "-srcfolder", staging,
         "-format", "UDZO", "-ov", image])


def checksums(output):
    files = sorted(path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt")
    lines = []
    for path in files:
        with path.open("rb") as source:
            hasher = hashlib.sha256()
            for block in iter(lambda: source.read(1024 * 1024), b""):
                hasher.update(block)
            digest = hasher.hexdigest()
        lines.append(digest + "  " + path.name)
    (output / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-freeze", action="store_true")
    args = parser.parse_args()
    system = platform.system()
    architecture = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    if system not in ("Windows", "Linux", "Darwin"):
        raise SystemExit("Gere o pacote nativamente em Windows, Linux ou macOS.")
    output = ROOT / "dist/releases"
    output.mkdir(parents=True, exist_ok=True)
    if not args.skip_freeze:
        freeze(system)
    if system == "Windows":
        windows(output)
    elif system == "Linux":
        linux(output, architecture)
    else:
        macos(output, architecture)
    checksums(output)
    print("Pacotes disponíveis em " + str(output))


if __name__ == "__main__":
    main()
