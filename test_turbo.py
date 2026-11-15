"""Automated verification suite for SI-ANR-Turbo against real ANR FG V.B18 files."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from si_anr_turbo import (
    apply_all_patches,
    audit_installation,
    resolve_anr_paths,
    rollback_backup,
    scan_anticheat,
)

ANR_EXTRACTED_GAME = Path(r"C:\YOUTUBE\TOOLS\anr-fg-V.B18\game")


class SiAnrTurboTests(unittest.TestCase):
    def setUp(self) -> None:
        if not ANR_EXTRACTED_GAME.exists():
            self.skipTest("Extracted anr-fg-V.B18/game folder not found")
        self.tmp = Path(tempfile.mkdtemp(prefix="si_anr_test_"))
        self.game_dir = self.tmp / "CyberGame"
        shutil.copytree(ANR_EXTRACTED_GAME, self.game_dir)
        (self.game_dir / "CyberGame.exe").write_bytes(b"MZ" + b"\x00" * 1024)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stock_audit_detects_real_v18_bugs(self) -> None:
        audit = audit_installation(self.game_dir)
        self.assertTrue(audit["ok"])
        self.assertGreaterEqual(audit["issue_count"], 6)
        ids = {i["id"] for i in audit["issues"]}
        self.assertIn("SIZE_TABLE_GAPS", ids)
        self.assertIn("VRAM_RINGBUFFER_FREEZE", ids)
        self.assertIn("TRACE_LOG_STUTTER", ids)
        self.assertIn("HUD_GHOSTING_EXPOSED", ids)
        self.assertIn("NO_FLIP_METERING", ids)

    def test_anticheat_blocks_injection(self) -> None:
        (self.game_dir / "EasyAntiCheat_EOS.exe").write_bytes(b"MZ" + b"\x00" * 64)
        scan = scan_anticheat(self.game_dir)
        self.assertFalse(scan["safe_to_inject"])
        res = apply_all_patches(self.game_dir)
        self.assertFalse(res["ok"])
        self.assertTrue(res.get("blocked_by_anticheat"))

    def test_apply_patches_and_sha256_rollback(self) -> None:
        res = apply_all_patches(self.game_dir, profile_key="rtx_30_20_8gb")
        self.assertTrue(res["ok"])
        self.assertEqual(res["remaining_issues"], 0)

        paths = resolve_anr_paths(self.game_dir)
        size_tbl = json.loads(paths["size_table"].read_text(encoding="utf-8"))
        ada = next(e for e in size_tbl["entries"] if e["vendor"] == "nvidia" and e["architecture"] == "ada")
        self.assertIn("2160p", ada["large"])
        self.assertTrue(any(e["vendor"] == "amd" and e["architecture"] == "rdna2" for e in size_tbl["entries"]))
        self.assertTrue(any(e["vendor"] == "intel" and e["architecture"] == "alchemist" for e in size_tbl["entries"]))

        nr_fg_txt = paths["nr_fg_ini"].read_text(encoding="utf-8")
        self.assertIn("max_generated = 1", nr_fg_txt)
        self.assertTrue(paths["launcher_cmd"].exists())
        self.assertIn("NR_BARRIER_ELIDE=1", paths["launcher_cmd"].read_text(encoding="utf-8"))

        opti_txt = paths["optiscaler_ini"].read_text(encoding="utf-8")
        self.assertIn("LogToFile=false", opti_txt)
        self.assertIn("DrawUIOverFG=true", opti_txt)
        self.assertIn("FramePacingTuning=true", opti_txt)
        self.assertIn("ForceReflex=2", opti_txt)

        rb = rollback_backup(self.game_dir)
        self.assertTrue(rb["ok"])
        self.assertFalse(paths["launcher_cmd"].exists())
        post_rb = audit_installation(self.game_dir)
        self.assertGreaterEqual(post_rb["issue_count"], 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
