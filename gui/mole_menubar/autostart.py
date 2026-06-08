from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from . import APP_IDENTIFIER


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path(label: str = APP_IDENTIFIER) -> Path:
    return launch_agents_dir() / f"{label}.plist"


def detect_launcher_args(mole_root: Path) -> list[str]:
    launcher = os.environ.get("MOLE_MENUBAR_LAUNCHER")
    if launcher:
        return [launcher]
    return [sys.executable, "-m", "mole_menubar", "--mole-root", str(mole_root)]


def build_plist(program_args: list[str], label: str = APP_IDENTIFIER) -> dict[str, object]:
    return {
        "Label": label,
        "ProgramArguments": program_args,
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(Path.home() / "Library" / "Logs" / "mole-menubar" / "launchd.out.log"),
        "StandardErrorPath": str(Path.home() / "Library" / "Logs" / "mole-menubar" / "launchd.err.log"),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        },
    }


class LoginItemManager:
    def __init__(self, label: str = APP_IDENTIFIER) -> None:
        self.label = label
        self.path = plist_path(label)

    def is_enabled(self) -> bool:
        return self.path.exists()

    def install(self, program_args: list[str]) -> None:
        launch_agents_dir().mkdir(parents=True, exist_ok=True)
        (Path.home() / "Library" / "Logs" / "mole-menubar").mkdir(parents=True, exist_ok=True)
        payload = build_plist(program_args, self.label)
        with self.path.open("wb") as handle:
            plistlib.dump(payload, handle, sort_keys=False)

    def remove(self) -> None:
        self._bootout()
        self.path.unlink(missing_ok=True)

    def _bootout(self) -> None:
        if not self.path.exists():
            return
        domain = f"gui/{os.getuid()}"
        subprocess.run(
            ["/bin/launchctl", "bootout", domain, str(self.path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage Mole Menu login autostart.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--enable", action="store_true")
    action.add_argument("--disable", action="store_true")
    action.add_argument("--status", action="store_true")
    parser.add_argument("--launcher", action="append", default=[])
    parser.add_argument("--label", default=APP_IDENTIFIER)
    args = parser.parse_args(argv)

    manager = LoginItemManager(args.label)
    if args.status:
        print("enabled" if manager.is_enabled() else "disabled")
        return 0
    if args.enable:
        if not args.launcher:
            parser.error("--enable requires at least one --launcher value")
        manager.install(args.launcher)
        return 0
    manager.remove()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
