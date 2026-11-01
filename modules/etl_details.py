import csv
import re


def parse_cpu_report(text):
    processes, threads = [], []
    thread_table = None
    for line in text.splitlines():
        if "Time (us)" in line and "Process Name" in line:
            thread_table = "ThreadID" in line
            continue
        if thread_table is None:
            continue
        match = re.fullmatch(r"\s*(\d+)\s*,\s*(.*?)\s*\(\s*(\d+)\s*\)\s*(?:,\s*(\d+)\s*)?", line)
        if not match:
            continue
        if thread_table and match[4] is None:
            continue
        row = {"cpu_us": int(match[1]), "name": match[2].strip()[:160], "pid": int(match[3])}
        if row["pid"] == 0:
            continue
        if thread_table:
            row["tid"] = int(match[4])
            threads.append(row)
        else:
            processes.append(row)
    return {"processes": sorted(processes, key=lambda row: row["cpu_us"], reverse=True),
            "threads": sorted(threads, key=lambda row: row["cpu_us"], reverse=True),
            "method": "Tempo de execução deduzido de trocas de contexto; soma CPUs. Não mede sozinho tempo pronto, espera ou causa da pausa."}


def parse_disk_report(text):
    rows, header = [], False
    for line in text.splitlines():
        cells = next(csv.reader([line], skipinitialspace=True))
        if not cells:
            continue
        if cells[0].strip() == "Count" and "Filename" in [c.strip() for c in cells]:
            header = True
            continue
        if not header or len(cells) < 11:
            continue
        try:
            count, size, read_count, read_size, write_count, write_size = (int(cells[i]) for i in (0, 1, 3, 4, 6, 7))
        except ValueError:
            continue
        if min(count, size, read_count, read_size, write_count, write_size) < 0:
            continue
        rows.append({"file": ",".join(cells[10:]).strip()[:800], "count": count, "bytes": size,
                     "read_count": read_count, "read_bytes": read_size, "write_count": write_count, "write_bytes": write_size})
    return {"files": sorted(rows, key=lambda row: row["bytes"], reverse=True),
            "method": "Contagens e bytes do relatório DiskIO por arquivo. Volume não é latência nem atribui defeito ao dispositivo."}


def parse_fault_report(text):
    files, processes = [], {}
    for line in text.splitlines():
        cells = next(csv.reader([line], skipinitialspace=True))
        if len(cells) < 4:
            continue
        try:
            count, size = int(cells[0]), int(cells[1])
        except ValueError:
            continue
        match = re.fullmatch(r"\s*(.*?)\s*\(\s*(\d+)\s*\)\s*", cells[2])
        if not match or min(count, size) < 0:
            continue
        name, pid = match[1].strip()[:160], int(match[2])
        key = (pid, name)
        summary = processes.setdefault(key, {"pid": pid, "name": name, "count": 0, "bytes": 0})
        summary["count"] += count
        summary["bytes"] += size
        files.append({"pid": pid, "name": name, "count": count, "bytes": size,
                      "file": ",".join(cells[3:]).strip()[:800]})
    return {"processes": sorted(processes.values(), key=lambda row: row["count"], reverse=True),
            "files": sorted(files, key=lambda row: row["count"], reverse=True),
            "method": "Hard faults exigem buscar páginas não residentes; não são erros físicos de RAM. O resumo não mede o tempo de resolução."}
