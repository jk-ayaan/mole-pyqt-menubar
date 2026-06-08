from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class MoleError(RuntimeError):
    """Raised when the Mole CLI cannot be run successfully."""


@dataclass(frozen=True)
class StatusSummary:
    health_score: int | None
    health_message: str
    cpu_percent: float | None
    memory_percent: float | None
    disk_percent: float | None
    uptime: str
    top_process: str

    @property
    def title(self) -> str:
        if self.health_score is None:
            return "Mole status unavailable"
        return f"Health {self.health_score} · CPU {format_percent(self.cpu_percent)}"

    @property
    def detail(self) -> str:
        return (
            f"Memory {format_percent(self.memory_percent)} · "
            f"Disk {format_percent(self.disk_percent)} · "
            f"Uptime {self.uptime or 'unknown'}"
        )


def format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0f}%"


def summarize_status(payload: dict[str, Any]) -> StatusSummary:
    memory = payload.get("memory") if isinstance(payload.get("memory"), dict) else {}
    cpu = payload.get("cpu") if isinstance(payload.get("cpu"), dict) else {}
    disks = payload.get("disks") if isinstance(payload.get("disks"), list) else []
    top_processes = payload.get("top_processes") if isinstance(payload.get("top_processes"), list) else []

    root_disk = None
    for disk in disks:
        if isinstance(disk, dict) and disk.get("mount") == "/":
            root_disk = disk
            break
    if root_disk is None and disks and isinstance(disks[0], dict):
        root_disk = disks[0]

    top_process = ""
    if top_processes and isinstance(top_processes[0], dict):
        name = str(top_processes[0].get("name") or "").strip()
        cpu_value = top_processes[0].get("cpu")
        if name:
            top_process = f"{name} {format_percent(as_float(cpu_value))}"

    return StatusSummary(
        health_score=as_int(payload.get("health_score")),
        health_message=str(payload.get("health_score_msg") or ""),
        cpu_percent=as_float(cpu.get("usage")),
        memory_percent=as_float(memory.get("used_percent")),
        disk_percent=as_float(root_disk.get("used_percent")) if root_disk else None,
        uptime=str(payload.get("uptime") or ""),
        top_process=top_process,
    )


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class MoleRunner:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.mo_path = self.root / "mo"

    def ensure_ready(self) -> None:
        if not self.mo_path.exists():
            raise MoleError(f"Missing Mole launcher: {self.mo_path}")
        if not os.access(self.mo_path, os.X_OK):
            raise MoleError(f"Mole launcher is not executable: {self.mo_path}")

    def status(self, timeout: float = 12.0) -> StatusSummary:
        payload = self.run_json(["status", "--json"], timeout=timeout)
        return summarize_status(payload)

    def run_json(self, args: Iterable[str], timeout: float = 20.0) -> dict[str, Any]:
        self.ensure_ready()
        env = os.environ.copy()
        env.setdefault("LC_ALL", "C")
        env.setdefault("LANG", "C")
        proc = subprocess.run(
            [str(self.mo_path), *args],
            cwd=str(self.root),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            message = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
            raise MoleError(message)
        try:
            decoded = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise MoleError(f"Invalid JSON from Mole: {exc}") from exc
        if not isinstance(decoded, dict):
            raise MoleError("Mole returned a non-object JSON payload")
        return decoded

    def open_command_in_terminal(self, args: Iterable[str], title: str) -> Path:
        self.ensure_ready()
        command_dir = Path.home() / ".cache" / "mole-menubar" / "commands"
        command_dir.mkdir(parents=True, exist_ok=True)
        script_path = command_dir / f"mole-{int(time.time())}.command"
        rendered_args = " ".join(shlex.quote(arg) for arg in args)
        script = "\n".join(
            [
                "#!/bin/bash",
                "set -e",
                f"cd {shlex.quote(str(self.root))}",
                "clear",
                f"echo {shlex.quote(title)}",
                "echo",
                f"{shlex.quote(str(self.mo_path))} {rendered_args}",
                "status=$?",
                "echo",
                "read -n 1 -s -r -p 'Press any key to close this window...'",
                "echo",
                "exit $status",
                "",
            ]
        )
        script_path.write_text(script, encoding="utf-8")
        script_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        subprocess.Popen(["/usr/bin/open", str(script_path)], cwd=str(self.root))
        return script_path

    def open_folder(self) -> None:
        subprocess.Popen(["/usr/bin/open", str(self.root)])
