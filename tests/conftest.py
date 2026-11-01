import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import gc
from PySide6.QtCore import QCoreApplication, QEvent
from shiboken6 import isValid
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    yield application
    application.processEvents()


@pytest.fixture(autouse=True)
def release_test_widgets(qt_application):
    yield
    for widget in qt_application.topLevelWidgets():
        if isValid(widget) and widget.parent() is None:
            shutdown = getattr(widget, "shutdown", None)
            if callable(shutdown):
                shutdown()
            widget.close()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_application.processEvents()
    gc.collect()
