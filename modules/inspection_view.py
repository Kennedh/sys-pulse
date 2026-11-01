import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QLineEdit, QComboBox, QTabWidget, QPlainTextEdit, QFileDialog)

from modules.analysis_view import table, fill
from modules.inspection import driver_rows, inspection_text


class InspectionPanel(QWidget):
    refresh_requested = Signal()

    def __init__(self):
        super().__init__()
        self.snapshot = None
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel("Drivers e saúde do sistema")
        title.setObjectName("title")
        heading.addWidget(title, 1)
        self.refresh_button = QPushButton("Atualizar inventário")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        heading.addWidget(self.refresh_button)
        self.export_button = QPushButton("Exportar JSON…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export)
        heading.addWidget(self.export_button)
        layout.addLayout(heading)
        self.status = QLabel("Consultando dispositivos, drivers, discos e eventos…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        drivers = QWidget()
        driver_layout = QVBoxLayout(drivers)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar dispositivo, classe, fornecedor, versão ou INF…")
        self.search.textChanged.connect(self.show_drivers)
        filters.addWidget(self.search, 1)
        self.filter = QComboBox()
        self.filter.addItems(["Todos", "Atenção", "Desativado", "Ausente", "N/D"])
        self.filter.currentTextChanged.connect(self.show_drivers)
        filters.addWidget(self.filter)
        driver_layout.addLayout(filters)
        self.drivers = table(["Dispositivo", "Classe", "Fornecedor", "Versão", "Data", "Assinado", "Status PnP", "INF"])
        driver_layout.addWidget(self.drivers)
        tabs.addTab(drivers, "Drivers")
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        tabs.addTab(self.details, "Saúde e eventos")
        note = QLabel("Consulta pontual do Windows. Data antiga não significa driver desatualizado.\n"
                      "Use os códigos e horários como evidência; latência por driver exige uma captura específica.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)

    def set_snapshot(self, snapshot):
        self.snapshot = snapshot
        self.refresh_button.setEnabled(True)
        self.export_button.setEnabled(True)
        sections = snapshot.get("sections", {})
        unavailable = [name for name, section in sections.items() if section.get("status") != "ok"]
        count = sum(row["status"] == "Atenção" for row in driver_rows(snapshot))
        status = f"Consulta: {snapshot.get('collected_at', 'N/D')} · {count} dispositivo(s) para revisar"
        if unavailable:
            status += " · Dados indisponíveis em: " + ", ".join(unavailable)
        if snapshot.get("demo"):
            status = "DADOS SIMULADOS · " + status
        self.status.setText(status)
        self.details.setPlainText(inspection_text(snapshot, include_drivers=False))
        self.show_drivers()

    def show_drivers(self, *_):
        query, status = self.search.text().strip().casefold(), self.filter.currentText()
        values = []
        for row in driver_rows(self.snapshot or {}):
            if query not in " ".join(str(v) for v in row.values()).casefold():
                continue
            if status != "Todos" and row["status"] != status:
                continue
            signed = "Sim" if row["signed"] is True else "Não" if row["signed"] is False else "N/D"
            values.append([row["name"], row["class"] or "N/D", row["provider"] or "N/D",
                           row["version"] or "N/D", row["date"] or "N/D", signed,
                           f"{row['status']} · {row['detail']}", row["inf"] or "N/D"])
        fill(self.drivers, values)

    def export(self):
        if not self.snapshot:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar inventário", "inventario.json", "JSON (*.json)")
        if path:
            try:
                Path(path).write_text(json.dumps(self.snapshot, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
                self.status.setText(f"Inventário exportado: {path}")
            except OSError as error:
                self.status.setText(f"Não foi possível exportar: {error}")
