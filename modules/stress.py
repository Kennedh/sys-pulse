import hashlib
import json
import multiprocessing
import os
import queue
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil


def write_json(path, data):
    temporary = Path(path).with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def validate_options(options):
    kind = options.get("kind")
    if kind not in ("cpu", "memory", "gpu"):
        raise ValueError("Escolha CPU, GPU ou RAM.")
    duration = int(options.get("duration_s", 900))
    workers = int(options.get("workers", min(64, os.cpu_count() or 1)))
    intensity = int(options.get("intensity", 50))
    memory = int(options.get("memory_mb", 256))
    if not 1 <= duration <= 7200 or not 1 <= workers <= min(64, os.cpu_count() or 1):
        raise ValueError("Duração ou quantidade de processos fora do limite.")
    if not 10 <= intensity <= 100 or not 16 <= memory <= 4096:
        raise ValueError("Carga ou quantidade de RAM fora do limite.")
    if kind == "memory" and memory * 1024 ** 2 > psutil.virtual_memory().available * .25:
        raise ValueError("A RAM escolhida excede 25% da memória disponível. Reduza a quantidade.")
    return {"kind": kind, "duration_s": duration, "workers": workers, "intensity": intensity, "memory_mb": memory}


def cpu_lane(stop, deadline, intensity, result):
    expected = bytes.fromhex("c5e478d59288c841aa530db6845c4c8d962893a001ce4e11a4963873aa98134a")
    checks = errors = 0
    try:
        while not stop.is_set() and time.monotonic() < deadline:
            started = time.monotonic()
            while time.monotonic() - started < .05 * intensity / 100 and not stop.is_set():
                value = hashlib.pbkdf2_hmac("sha256", b"password", b"salt", 4096)
                checks += 1
                if value != expected:
                    errors += 1
                    stop.set()
                    break
            stop.wait(max(0, .05 - (time.monotonic() - started)))
        result.put({"checks": checks, "errors": errors})
    except BaseException as error:
        result.put({"checks": checks, "errors": errors, "failure": type(error).__name__})


def parent_alive(config):
    try:
        parent = psutil.Process(config["parent_pid"])
        return abs(parent.create_time() - config["parent_created"]) < .1 and parent.is_running()
    except (psutil.Error, KeyError):
        return False


def run_worker(folder):
    folder = Path(folder).resolve()
    config = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    options = validate_options(config)
    if options["kind"] == "gpu":
        from modules.stress_gpu import run_gpu
        return run_gpu(folder, config)
    try:
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 5)
    except psutil.Error:
        pass
    started = time.monotonic()
    deadline = started + options["duration_s"]
    result = {"kind": options["kind"], "state": "running", "checks": 0, "errors": 0,
              "elapsed_s": 0, "reason": "Duração concluída", "options": options,
              "started_monotonic": started}
    context = multiprocessing.get_context("spawn")
    stop, reports, children = context.Event(), context.Queue(), []
    memory = None
    try:
        if options["kind"] == "cpu":
            for _ in range(options["workers"]):
                process = context.Process(target=cpu_lane, args=(stop, deadline, options["intensity"], reports))
                process.start()
                children.append(process)
        else:
            memory = bytearray(options["memory_mb"] * 1024 ** 2)
        while time.monotonic() < deadline and not stop.is_set():
            if (folder / "stop").exists() or not parent_alive(config):
                result["reason"] = "Parada solicitada ou aplicativo encerrado"
                break
            if memory is not None:
                cycle = time.monotonic()
                pattern = bytes([0x55 if result["checks"] % 2 else 0xAA]) * (1024 ** 2)
                for offset in range(0, len(memory), len(pattern)):
                    if time.monotonic() >= deadline or (folder / "stop").exists():
                        break
                    memory[offset:offset + len(pattern)] = pattern
                    if memoryview(memory)[offset:offset + len(pattern)] != pattern:
                        result["errors"] += 1
                        stop.set()
                        break
                    result["checks"] += 1
                work = time.monotonic() - cycle
                time.sleep(min(.25, max(0, work * (100 / options["intensity"] - 1))))
            else:
                while True:
                    try:
                        report = reports.get_nowait()
                        result["checks"] += report["checks"]
                        result["errors"] += report["errors"]
                        if report.get("failure"):
                            raise RuntimeError("Um processo de carga falhou: " + report["failure"])
                    except queue.Empty:
                        break
                if children and all(not process.is_alive() for process in children):
                    break
                time.sleep(.2)
            result["elapsed_s"] = time.monotonic() - started
            write_json(folder / "progress.json", result)
        stop.set()
        for process in children:
            process.join(timeout=3)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
            if process.exitcode:
                raise RuntimeError(f"Processo de carga encerrou com código {process.exitcode}.")
        while True:
            try:
                report = reports.get(timeout=.1)
                result["checks"] += report["checks"]
                result["errors"] += report["errors"]
                if report.get("failure"):
                    raise RuntimeError("Um processo de carga falhou: " + report["failure"])
            except queue.Empty:
                break
        result["state"] = "failed" if result["errors"] else "stopped" if time.monotonic() < deadline - .5 else "completed"
        if result["errors"]:
            result["reason"] = "Divergência na verificação; teste interrompido."
    except BaseException as error:
        result.update(state="failed", reason=f"{type(error).__name__}: {error}")
    finally:
        stop.set()
        for process in children:
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
        reports.close()
        reports.join_thread()
        result["elapsed_s"] = time.monotonic() - started
        result["ended_monotonic"] = time.monotonic()
        result["method"] = ("PBKDF2-SHA256 com resultado conhecido por processo." if memory is None else
                            "Escrita e leitura de padrões 0xAA/0x55 em RAM virtual alocada, por blocos de 1 MiB. Não é MemTest de toda a RAM.")
        write_json(folder / "result.json", result)
    return 0 if result["state"] in ("completed", "stopped") else 1


class StressController:
    def __init__(self):
        self.process = None
        self.path = None
        self.log = None

    def start(self, folder, options):
        options = validate_options(options)
        self.path = Path(folder) / ("carga-" + uuid.uuid4().hex[:12])
        self.path.mkdir()
        parent = psutil.Process()
        write_json(self.path / "request.json", {**options, "parent_pid": os.getpid(), "parent_created": parent.create_time()})
        root = Path(__file__).resolve().parents[1]
        command = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, str(root / "main.py")]
        self.log = (self.path / "worker.log").open("wb")
        try:
            self.process = subprocess.Popen([*command, "--stress-worker", str(self.path)],
                stdout=self.log, stderr=subprocess.STDOUT, creationflags=0x08000000 if os.name == "nt" else 0)
        except BaseException:
            self.log.close()
            raise
        return self.path

    def status(self):
        if not self.path:
            return {}
        filename = "result.json" if (self.path / "result.json").is_file() else "progress.json"
        try:
            path = self.path / filename
            if path.stat().st_size > 65536:
                return {}
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def stop(self):
        if self.path:
            (self.path / "stop").touch()

    def close(self):
        self.stop()
        if self.process and self.process.poll() is None:
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                parent = psutil.Process(self.process.pid)
                for process in parent.children(recursive=True):
                    try:
                        process.terminate()
                    except psutil.Error:
                        pass
                self.process.terminate()
                self.process.wait(timeout=3)
        if self.log:
            self.log.close()
