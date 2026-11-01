import json
import os
import platform
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from modules.ai_service import NoRedirect, request_json, validate_endpoint


LOCAL_MODELS = (
    ("llama3.2:1b", "Llama 3.2 1B · compacto · download ~1,3 GB", 1_300_000_000),
    ("llama3.2:3b", "Llama 3.2 3B · teste documentado · download ~2 GB", 2_100_000_000),
    ("qwen3:0.6b", "Qwen 3 0.6B · download ~523 MB · qualidade a validar", 550_000_000),
)


class DownloadCancelled(Exception):
    pass


def ollama_base(endpoint):
    endpoint, local = validate_endpoint(endpoint)
    if not local or urllib.parse.urlsplit(endpoint).path != "/api/chat":
        raise ValueError("Gerencie modelos somente na API local do Ollama.")
    return endpoint[:-len("/chat")]


def validate_model(name):
    name = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,150}(?::[A-Za-z0-9][A-Za-z0-9._-]{0,50})?", name):
        raise ValueError("Informe um nome de modelo do catálogo do Ollama, sem endereço ou opções.")
    if ".." in name.split("/") or "//" in name:
        raise ValueError("Nome de modelo inválido.")
    return name


def cloud_model(name):
    return name.endswith(("-cloud", ":cloud"))


def find_ollama():
    executable = shutil.which("ollama")
    if executable:
        return executable
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe",
        Path("/Applications/Ollama.app/Contents/Resources/ollama"),
        Path("/usr/local/bin/ollama"),
    ]
    return next((str(path) for path in candidates if path.is_file()), None)


def runtime_url():
    system = platform.system()
    return "https://ollama.com/download/" + {"Windows": "windows", "Darwin": "mac"}.get(system, "linux")


def pull_model(endpoint, name, progress, cancelled):
    base = ollama_base(endpoint)
    name = validate_model(name)
    request = urllib.request.Request(base + "/pull",
        data=json.dumps({"model": name, "stream": True}).encode(),
        headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    if cancelled():
        raise DownloadCancelled()
    try:
        with opener.open(request, timeout=15) as response:
            for _ in range(200_000):
                if cancelled():
                    raise DownloadCancelled()
                line = response.readline(65_537)
                if len(line) > 65_536:
                    raise ValueError("Resposta de download excedeu o limite de leitura.")
                if not line:
                    break
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ValueError("Resposta de download inválida.")
                if item.get("error"):
                    raise RuntimeError(str(item["error"])[:300])
                progress(item)
                if item.get("status") == "success":
                    return name
    except (urllib.error.URLError, TimeoutError) as error:
        if cancelled():
            raise DownloadCancelled() from None
        raise RuntimeError("O download não concluiu. Confira o Ollama e a conexão; tente novamente para aproveitar as camadas já baixadas.") from error
    if cancelled():
        raise DownloadCancelled()
    raise RuntimeError("O Ollama encerrou a resposta sem confirmar o download.")


class OllamaRuntime:
    def __init__(self):
        self.process = None
        self._lock = threading.Lock()

    def start(self, endpoint, cancelled):
        if cancelled():
            raise DownloadCancelled()
        base = ollama_base(endpoint)
        try:
            return request_json(base + "/version", timeout=2)
        except RuntimeError:
            pass
        parsed = urllib.parse.urlsplit(base)
        if parsed.port != 11434:
            raise ValueError("Inicie o servidor personalizado pelo próprio Ollama.")
        executable = find_ollama()
        if not executable:
            raise ValueError("Instale o Ollama pelo botão Baixar Ollama e tente novamente.")
        with self._lock:
            if cancelled():
                raise DownloadCancelled()
            if not self.process or self.process.poll() is not None:
                environment = {**os.environ, "OLLAMA_HOST": "127.0.0.1:11434"}
                self.process = subprocess.Popen([executable, "serve"], env=environment,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=0x08000000 if os.name == "nt" else 0)
        for _ in range(40):
            if cancelled():
                raise DownloadCancelled()
            try:
                return request_json(base + "/version", timeout=1)
            except RuntimeError:
                time.sleep(.25)
        raise RuntimeError("O servidor ainda não respondeu. Abra o Ollama e tente novamente.")

    def signin(self, endpoint, cancelled):
        ollama_base(endpoint)
        executable = find_ollama()
        if not executable:
            raise ValueError("Instale o Ollama para entrar na sua conta.")
        with subprocess.Popen([executable, "signin"], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              creationflags=0x08000000 if os.name == "nt" else 0) as process:
            deadline = time.monotonic() + 180
            while process.poll() is None:
                if cancelled() or time.monotonic() > deadline:
                    process.terminate()
                    process.wait(timeout=5)
                    if cancelled():
                        raise DownloadCancelled()
                    raise RuntimeError("Conclua o login no Ollama e tente novamente.")
                time.sleep(.2)
            if process.returncode:
                raise RuntimeError("O login não concluiu. Entre pela janela do Ollama e tente novamente.")
        return {"message": "Login solicitado ao Ollama. Conclua no navegador; a próxima análise confirma o acesso. Nenhuma chave foi copiada."}

    def close(self):
        with self._lock:
            process, self.process = self.process, None
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
