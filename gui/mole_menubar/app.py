from __future__ import annotations

import argparse
import fcntl
import logging
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import APP_NAME
from .autostart import LoginItemManager, detect_launcher_args
from .mole import MoleError, MoleRunner, StatusSummary


REFRESH_INTERVAL_MS = 15_000


def setup_logging() -> None:
    log_dir = Path.home() / "Library" / "Logs" / "mole-menubar"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_dir / "app.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def acquire_lock() -> object | None:
    lock_dir = Path.home() / "Library" / "Application Support" / "Mole Menu"
    lock_dir.mkdir(parents=True, exist_ok=True)
    handle = (lock_dir / "mole-menu.lock").open("w", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return None
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


class StatusWorker(QObject):
    finished = pyqtSignal(object, object)

    def __init__(self, runner: MoleRunner) -> None:
        super().__init__()
        self.runner = runner

    def run(self) -> None:
        try:
            self.finished.emit(self.runner.status(), None)
        except Exception as exc:  # noqa: BLE001 - surfaced in the menu and log.
            self.finished.emit(None, exc)


class MoleMenuApp(QObject):
    def __init__(self, app: QApplication, root: Path) -> None:
        super().__init__()
        self.app = app
        self.root = root
        self.runner = MoleRunner(root)
        self.login_items = LoginItemManager()
        self.tray = QSystemTrayIcon(make_tray_icon(QColor("#2b7a78")), self.app)
        self.tray.setToolTip(f"{APP_NAME}: starting...")
        self.menu = QMenu()
        self.status_action = QAction("Loading Mole status...", self.menu)
        self.status_action.setEnabled(False)
        self.detail_action = QAction("", self.menu)
        self.detail_action.setEnabled(False)
        self.top_process_action = QAction("", self.menu)
        self.top_process_action.setEnabled(False)
        self.autostart_action = QAction("Open at Login", self.menu)
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(self.login_items.is_enabled())
        self.autostart_action.toggled.connect(self.set_autostart)
        self.refresh_action = QAction("Refresh Status", self.menu)
        self.refresh_action.triggered.connect(self.refresh_status)
        self._thread: QThread | None = None
        self._worker: StatusWorker | None = None
        self._build_menu()

        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()
        logging.info("Mole Menu started with root %s", self.root)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(REFRESH_INTERVAL_MS)
        self.refresh_status()

    def _build_menu(self) -> None:
        self.menu.addAction(self.status_action)
        self.menu.addAction(self.detail_action)
        self.menu.addAction(self.top_process_action)
        self.menu.addSeparator()
        self.menu.addAction(self.refresh_action)

        clean_preview = QAction("Preview Clean", self.menu)
        clean_preview.triggered.connect(lambda: self.open_terminal(["clean", "--dry-run"], "Mole clean preview"))
        self.menu.addAction(clean_preview)

        optimize_preview = QAction("Preview Optimize", self.menu)
        optimize_preview.triggered.connect(
            lambda: self.open_terminal(["optimize", "--dry-run"], "Mole optimize preview")
        )
        self.menu.addAction(optimize_preview)

        analyze_home = QAction("Analyze Home Folder", self.menu)
        analyze_home.triggered.connect(lambda: self.open_terminal(["analyze", str(Path.home())], "Mole disk analyzer"))
        self.menu.addAction(analyze_home)

        status_dashboard = QAction("Open Terminal Dashboard", self.menu)
        status_dashboard.triggered.connect(lambda: self.open_terminal(["status"], "Mole status dashboard"))
        self.menu.addAction(status_dashboard)

        history = QAction("Open Cleanup History", self.menu)
        history.triggered.connect(lambda: self.open_terminal(["history"], "Mole cleanup history"))
        self.menu.addAction(history)

        self.menu.addSeparator()
        self.menu.addAction(self.autostart_action)

        open_folder = QAction("Open Mole Folder", self.menu)
        open_folder.triggered.connect(self.runner.open_folder)
        self.menu.addAction(open_folder)

        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(self.app.quit)
        self.menu.addAction(quit_action)

    def on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.refresh_status()

    def open_terminal(self, args: list[str], title: str) -> None:
        try:
            self.runner.open_command_in_terminal(args, title)
        except Exception as exc:  # noqa: BLE001 - menu action should not crash the app.
            logging.exception("Failed to open terminal command")
            self.tray.showMessage(APP_NAME, str(exc), QSystemTrayIcon.MessageIcon.Warning, 5000)

    def set_autostart(self, enabled: bool) -> None:
        try:
            if enabled:
                self.login_items.install(detect_launcher_args(self.root))
            else:
                self.login_items.remove()
        except Exception as exc:  # noqa: BLE001
            logging.exception("Failed to update autostart")
            self.autostart_action.blockSignals(True)
            self.autostart_action.setChecked(not enabled)
            self.autostart_action.blockSignals(False)
            self.tray.showMessage(APP_NAME, str(exc), QSystemTrayIcon.MessageIcon.Warning, 5000)

    def refresh_status(self) -> None:
        if self._thread is not None:
            return
        self.refresh_action.setEnabled(False)
        self._thread = QThread()
        self._worker = StatusWorker(self.runner)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self.on_status_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self.clear_worker)
        self._thread.start()

    def clear_worker(self) -> None:
        self._thread = None
        self._worker = None
        self.refresh_action.setEnabled(True)

    def on_status_finished(self, summary: object, error: object) -> None:
        if error is not None:
            self.set_error(error)
            return
        if isinstance(summary, StatusSummary):
            self.set_status(summary)

    def set_error(self, error: object) -> None:
        message = str(error)
        logging.warning("Status refresh failed: %s", message)
        self.status_action.setText("Status unavailable")
        self.detail_action.setText(message[:90])
        self.top_process_action.setText("")
        self.tray.setIcon(make_tray_icon(QColor("#b42318")))
        self.tray.setToolTip(f"{APP_NAME}: {message[:120]}")

    def set_status(self, summary: StatusSummary) -> None:
        color = QColor("#2e7d32")
        if summary.health_score is not None and summary.health_score < 70:
            color = QColor("#f59f00")
        if summary.health_score is not None and summary.health_score < 45:
            color = QColor("#b42318")
        self.tray.setIcon(make_tray_icon(color))
        self.status_action.setText(summary.title)
        self.detail_action.setText(summary.detail)
        top = f"Top process: {summary.top_process}" if summary.top_process else summary.health_message
        self.top_process_action.setText(top[:90])
        self.tray.setToolTip(f"{APP_NAME}: {summary.title}\n{summary.detail}")


def make_tray_icon(color: QColor) -> QIcon:
    pixmap = QPixmap(22, 22)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(color)
    painter.setPen(QColor("#ffffff"))
    painter.drawEllipse(2, 2, 18, 18)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(pixmap.rect(), 0x84, "M")
    painter.end()
    return QIcon(pixmap)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Mole PyQt6 menu bar app.")
    parser.add_argument("--mole-root", default=os.environ.get("MOLE_MENUBAR_ROOT", "."))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    lock = acquire_lock()
    if lock is None:
        logging.info("Another Mole Menu instance is already running")
        return 0

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        logging.error("System tray is not available")
        return 1
    MoleMenuApp(app, Path(args.mole_root))
    return app.exec()
