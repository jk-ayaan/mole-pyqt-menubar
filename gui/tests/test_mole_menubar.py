from __future__ import annotations

import plistlib
import unittest

from mole_menubar.autostart import build_plist
from mole_menubar.mole import summarize_status


class StatusSummaryTests(unittest.TestCase):
    def test_summarize_status_uses_root_disk_and_top_process(self) -> None:
        summary = summarize_status(
            {
                "health_score": 91,
                "health_score_msg": "All clear",
                "uptime": "3d",
                "cpu": {"usage": 12.4},
                "memory": {"used_percent": 55.2},
                "disks": [
                    {"mount": "/Volumes/External", "used_percent": 88.0},
                    {"mount": "/", "used_percent": 61.5},
                ],
                "top_processes": [{"name": "Code", "cpu": 18.1}],
            }
        )

        self.assertEqual(summary.health_score, 91)
        self.assertEqual(summary.disk_percent, 61.5)
        self.assertEqual(summary.top_process, "Code 18%")


class AutostartPlistTests(unittest.TestCase):
    def test_build_plist_is_launchd_readable(self) -> None:
        payload = build_plist(["/Applications/Mole Menu.app/Contents/MacOS/MoleMenu"])
        encoded = plistlib.dumps(payload)
        decoded = plistlib.loads(encoded)

        self.assertEqual(decoded["Label"], "io.github.mole.pyqt-menubar")
        self.assertTrue(decoded["RunAtLoad"])
        self.assertEqual(decoded["ProgramArguments"][0], "/Applications/Mole Menu.app/Contents/MacOS/MoleMenu")


if __name__ == "__main__":
    unittest.main()
