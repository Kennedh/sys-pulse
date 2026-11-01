import json
import platform
import subprocess
import threading
from datetime import datetime
from pathlib import Path


PNP_CODES = {
    0: "Sem erro informado", 1: "Configuração incorreta", 10: "Dispositivo não inicia",
    12: "Recursos insuficientes", 14: "Reinicialização necessária", 18: "Reinstalação solicitada",
    19: "Configuração de registro inválida", 21: "Remoção em andamento", 22: "Desativado",
    24: "Ausente ou não funciona", 28: "Driver não instalado", 31: "Driver não carregado",
    32: "Serviço desativado", 37: "Falha ao inicializar driver", 39: "Driver não carregado",
    43: "Dispositivo informou problema", 45: "Desconectado", 48: "Driver bloqueado",
    52: "Assinatura não verificada pelo Windows",
}
SECTIONS = ("devices", "drivers", "storage", "events")
SOURCES = {"devices": "Win32_PnPEntity", "drivers": "Win32_PnPSignedDriver",
           "storage": "Get-PhysicalDisk / Get-StorageReliabilityCounter", "events": "Get-WinEvent / System"}


def rows(value):
    return [row for row in (value if isinstance(value, list) else [value]) if isinstance(row, dict)]


def driver_rows(snapshot):
    sections = snapshot.get("sections", {})
    devices = rows(sections.get("devices", {}).get("rows", []))
    drivers = rows(sections.get("drivers", {}).get("rows", []))
    indexed = {str(row.get("DeviceID") or "").casefold(): row for row in devices if row.get("DeviceID")}
    result, seen = [], set()
    for driver in drivers + [{"DeviceID": d.get("DeviceID")} for d in devices]:
        identity = str(driver.get("DeviceID") or "")
        key = identity.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        device = indexed.get(key, {})
        code = device.get("ConfigManagerErrorCode")
        code = code if isinstance(code, int) and not isinstance(code, bool) else None
        signed = driver.get("IsSigned")
        signed = signed if isinstance(signed, bool) else None
        if device.get("Present") is False or code == 45:
            level = "Ausente"
        elif code == 22:
            level = "Desativado"
        elif code not in (None, 0) or signed is False:
            level = "Atenção"
        elif code == 0:
            level = "Sem erro PnP"
        else:
            level = "N/D"
        detail = f"Código {code}: {PNP_CODES.get(code, 'Consulte o Gerenciador de Dispositivos')}" if code is not None else "Status PnP indisponível"
        if signed is False:
            detail += " · WMI informa driver sem assinatura"
        result.append({"id": identity, "name": driver.get("DeviceName") or device.get("Name") or identity,
                       "class": driver.get("DeviceClass") or device.get("PNPClass"),
                       "provider": driver.get("DriverProviderName"), "version": driver.get("DriverVersion"),
                       "date": driver.get("DriverDate"), "signed": signed, "inf": driver.get("InfName"),
                       "code": code, "status": level, "detail": detail})
    return sorted(result, key=lambda row: (row["status"] != "Atenção", str(row["name"]).casefold()))


def inspection_text(snapshot, include_drivers=True):
    if not snapshot:
        return "Inventário não registrado nesta sessão."
    lines = [f"INVENTÁRIO · {snapshot.get('collected_at', 'N/D')}",
             "Consulta pontual; não é uma medição de latência nem valida a versão mais recente dos drivers."]
    for name, title in (("devices", "Dispositivos"), ("drivers", "Drivers"), ("storage", "Armazenamento"), ("events", "Eventos")):
        section = snapshot.get("sections", {}).get(name, {})
        lines.append(f"{title}: {section.get('status', 'indisponível')} · {len(rows(section.get('rows', [])))} registros · {SOURCES[name]}")
        if section.get("error"):
            lines.append(str(section["error"]))
    if include_drivers:
        lines += ["", "DRIVERS E DISPOSITIVOS"]
    for row in driver_rows(snapshot) if include_drivers else []:
        signed = "Sim" if row["signed"] is True else "Não" if row["signed"] is False else "N/D"
        lines.append(f"{row['name']} | {row['status']} | {row['detail']} | versão {row['version'] or 'N/D'} | "
                     f"fornecedor {row['provider'] or 'N/D'} | assinatura informada: {signed}")
    lines += ["", "ARMAZENAMENTO"]
    for disk in rows(snapshot.get("sections", {}).get("storage", {}).get("rows", [])):
        health = disk.get("HealthStatus")
        lines.append(f"{disk.get('FriendlyName', 'N/D')} · disco {disk.get('DeviceId', 'N/D')} | "
                     f"saúde informada: {health if health not in (None, '') else 'N/D'} | operação: {disk.get('OperationalStatus', 'N/D')}")
        reliability = disk.get("Reliability") or {}
        for field in ("Temperature", "Wear", "PowerOnHours", "ReadErrorsUncorrected", "WriteErrorsUncorrected"):
            value = reliability.get(field)
            lines.append(f"  {field}: {value if value is not None else 'N/D'}")
        if disk.get("ReliabilityError"):
            lines.append(f"  Contadores indisponíveis: {disk['ReliabilityError']}")
    lines += ["", "EVENTOS DO SISTEMA · até 100 ocorrências selecionadas das últimas 24 h"]
    for event in rows(snapshot.get("sections", {}).get("events", {}).get("rows", [])):
        lines.append(f"{event.get('TimeCreated', 'N/D')} | {event.get('ProviderName', 'N/D')} | ID {event.get('Id', 'N/D')}\n"
                     f"{event.get('Message') or 'Mensagem indisponível'}")
    lines += ["", "Data antiga não comprova driver desatualizado. Assinatura é a informação do WMI, não auditoria do arquivo.",
              "Desativado ou desconectado pode ser intencional. Para código de erro, confira o dispositivo no Gerenciador de Dispositivos.",
              "Saúde informada pelo Windows não substitui SMART completo nem teste físico. USB/RAID podem ocultar contadores.",
              "Eventos são históricos e podem anteceder a captura. Kernel-Power 41 não identifica a causa do desligamento.",
              "Para atribuir latência a drivers, faça uma captura específica com WPR/WPA ou LatencyMon."]
    return "\n".join(lines)


def inspect_system():
    snapshot = {"schema_version": 1, "collected_at": datetime.now().astimezone().isoformat(),
                "system": platform.system(), "sources": dict(SOURCES), "sections": {}}
    if platform.system() != "Windows":
        snapshot["sections"] = {name: {"status": "não suportado neste sistema", "rows": []} for name in SECTIONS}
        return snapshot
    try:
        script = Path(__file__).with_name("inspect_windows.ps1").read_text(encoding="utf-8")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, encoding="utf-8-sig", errors="replace",
                                timeout=45, creationflags=0x08000000)
        if result.returncode:
            raise ValueError(result.stderr.strip()[:500] or "PowerShell não concluiu a consulta")
        sections = json.loads(result.stdout)
        if not isinstance(sections, dict):
            raise ValueError("Resposta de inventário inválida")
        for name in SECTIONS:
            section = sections.get(name)
            if not isinstance(section, dict) or section.get("status") not in ("ok", "erro"):
                section = {"status": "erro", "error": "Resposta ausente ou inválida", "rows": []}
            section["rows"] = rows(section.get("rows", []))
            snapshot["sections"][name] = section
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        snapshot["sections"] = {name: {"status": "erro", "error": f"Inventário indisponível: {error}", "rows": []}
                                for name in SECTIONS}
    snapshot["collected_at"] = datetime.now().astimezone().isoformat()
    return snapshot


class InspectionService:
    def __init__(self, on_ready):
        self.on_ready = on_ready
        self._thread = None
        self._closed = threading.Event()

    def refresh(self):
        if self._closed.is_set() or self._thread and self._thread.is_alive():
            return False
        self._thread = threading.Thread(target=self._run, name="sys-pulse-inspection", daemon=True)
        self._thread.start()
        return True

    def _run(self):
        snapshot = inspect_system()
        if not self._closed.is_set():
            self.on_ready(snapshot)

    def stop(self):
        self._closed.set()
