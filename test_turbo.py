"""Automated verification suite for SI-ANR-Turbo v2.0 (Native x64 DLL Smart-Shield + 1-Click Installer)."""

import ctypes
import json
import shutil
import struct
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from si_anr_turbo import (
    SHIM_DLL_SOURCE,
    apply_all_patches,
    audit_installation,
    one_click_setup_and_patch,
    resolve_anr_paths,
    rollback_backup,
    scan_anticheat,
    sha256_file,
)
from turbo_system import detect_system_gpu, discover_installed_games, read_live_telemetry

ANR_EXTRACTED_GAME = Path(r"C:\YOUTUBE\TOOLS\anr-fg-V.B18\game")
MOCK_CORE_DLL = Path(__file__).resolve().parent / "native" / "bin" / "mock_core_dll.dll"


def _read_pe_exports(path: Path) -> list[str]:
    b = path.read_bytes()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    nsec = struct.unpack_from("<H", b, pe + 6)[0]
    opt = struct.unpack_from("<H", b, pe + 20)[0]
    sec_off = pe + 24 + opt
    secs = [struct.unpack_from("<8sIIII", b, sec_off + i * 40) for i in range(nsec)]
    secs_norm = [(va, rsz, rptr) for _, _, va, rsz, rptr in secs]

    def _r2o(rva: int) -> int | None:
        for va, rsz, rptr in secs_norm:
            if va <= rva < va + max(rsz, 1):
                return rptr + (rva - va)
        return None

    exp_rva = struct.unpack_from("<I", b, pe + 24 + 112)[0]
    exp_off = _r2o(exp_rva)
    assert exp_off is not None
    nnames = struct.unpack_from("<I", b, exp_off + 24)[0]
    names_off = _r2o(struct.unpack_from("<I", b, exp_off + 32)[0])
    assert names_off is not None
    out = []
    for i in range(nnames):
        nrva = struct.unpack_from("<I", b, names_off + i * 4)[0]
        off = _r2o(nrva)
        assert off is not None
        out.append(b[off:].split(b"\x00", 1)[0].decode("ascii"))
    return sorted(out)


class SiAnrTurboTests(unittest.TestCase):
    def setUp(self) -> None:
        if not ANR_EXTRACTED_GAME.exists():
            self.skipTest("Extracted anr-fg-V.B18/game folder not found")
        self.tmp = Path(tempfile.mkdtemp(prefix="si_anr_v2_test_"))
        self.game_dir = self.tmp / "CyberGame"
        shutil.copytree(ANR_EXTRACTED_GAME, self.game_dir)
        (self.game_dir / "CyberGame.exe").write_bytes(b"MZ" + b"\x00" * 1024)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stock_audit_detects_real_v18_bugs_and_missing_shim(self) -> None:
        audit = audit_installation(self.game_dir)
        self.assertTrue(audit["ok"])
        self.assertGreaterEqual(audit["issue_count"], 7)
        self.assertFalse(audit["native_shim_active"])
        ids = {i["id"] for i in audit["issues"]}
        self.assertIn("NATIVE_DLL_SHIELD_MISSING", ids)
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

    def test_apply_patches_native_dll_and_sha256_rollback(self) -> None:
        paths = resolve_anr_paths(self.game_dir)
        orig_dll_sha = sha256_file(paths["nvngx_dlssg_dll"])

        res = apply_all_patches(
            self.game_dir,
            profile_key="rtx_30_20_8gb",
            options={"gamepass_vulkan_spoof": True},
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["remaining_issues"], 0)
        self.assertTrue(paths["nvngx_dlssg_core_dll"].exists())
        self.assertEqual(sha256_file(paths["nvngx_dlssg_core_dll"]), orig_dll_sha)
        self.assertEqual(sha256_file(paths["nvngx_dlssg_dll"]), sha256_file(SHIM_DLL_SOURCE))
        self.assertIn("EnableBarrierElide=1", paths["dll_shield_ini"].read_text(encoding="utf-8"))

        size_tbl = json.loads(paths["size_table"].read_text(encoding="utf-8"))
        ada = next(e for e in size_tbl["entries"] if e["vendor"] == "nvidia" and e["architecture"] == "ada")
        self.assertIn("2160p", ada["large"])
        self.assertTrue(any(e["vendor"] == "amd" and e["architecture"] == "rdna2" for e in size_tbl["entries"]))
        self.assertTrue(any(e["vendor"] == "intel" and e["architecture"] == "alchemist" for e in size_tbl["entries"]))

        path_tbl = json.loads(paths["path_table"].read_text(encoding="utf-8"))
        bm = next(e for e in path_tbl["entries"] if e["vendor"] == "intel" and e["architecture"] == "battlemage")
        self.assertIn("0xb080", [x.lower() for x in bm.get("device_ids", [])])

        nr_fg_txt = paths["nr_fg_ini"].read_text(encoding="utf-8")
        self.assertIn("max_generated = 1", nr_fg_txt)
        self.assertIn("NR_BARRIER_ELIDE=1", paths["launcher_cmd"].read_text(encoding="utf-8"))

        opti_txt = paths["optiscaler_ini"].read_text(encoding="utf-8")
        self.assertIn("LogToFile=false", opti_txt)
        self.assertIn("DrawUIOverFG=true", opti_txt)
        self.assertIn("DisableUI=false", opti_txt)
        self.assertIn("FramePacingTuning=true", opti_txt)
        self.assertIn("ForceReflex=2", opti_txt)
        self.assertIn("StreamlineSpoofing=true", opti_txt)

        rb = rollback_backup(self.game_dir)
        self.assertTrue(rb["ok"])
        self.assertFalse(paths["launcher_cmd"].exists())
        self.assertFalse(paths["nvngx_dlssg_core_dll"].exists())
        self.assertFalse(paths["dll_shield_ini"].exists())
        self.assertEqual(sha256_file(paths["nvngx_dlssg_dll"]), orig_dll_sha)
        post_rb = audit_installation(self.game_dir)
        self.assertGreaterEqual(post_rb["issue_count"], 7)

    def test_oneclick_fresh_game_vulkan_detection_from_zip(self) -> None:
        fresh_game = self.tmp / "VulkanFreshGame"
        fresh_game.mkdir()
        (fresh_game / "Game.exe").write_bytes(b"MZ" + b"\x00" * 512)
        (fresh_game / "vulkan-1.dll").write_bytes(b"MZ" + b"\x00" * 128)

        # Build a realistic official-style archive from local extracted ANR V.B18 files
        fake_cache = self.tmp / "cache"
        fake_cache.mkdir()
        zip_path = fake_cache / "anr-fg-V.B18-full.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item in ANR_EXTRACTED_GAME.rglob("*"):
                if item.is_file():
                    zf.write(item, arcname=f"game/{item.relative_to(ANR_EXTRACTED_GAME).as_posix()}")

        with mock.patch("turbo_system.LOCAL_CACHE_DIR", fake_cache), mock.patch(
            "turbo_system.get_official_anr_download_info",
            return_value={"tag": "FG-V.B18", "filename": "anr-fg-V.B18-full.zip", "url": "https://example.invalid/anr.zip"},
        ):
            res = one_click_setup_and_patch(fresh_game, profile_key="amd_rdna3_4")
        self.assertTrue(res["ok"])
        self.assertEqual(res["official_install"]["loader_dll"], "winmm.dll")
        self.assertTrue((fresh_game / "winmm.dll").exists())
        self.assertTrue(audit_installation(fresh_game)["native_shim_active"])

    def test_native_dll_exports_and_inprocess_guards(self) -> None:
        if not MOCK_CORE_DLL.exists():
            self.skipTest("mock_core_dll.dll not built")
        official_dll = resolve_anr_paths(ANR_EXTRACTED_GAME)["nvngx_dlssg_dll"]
        self.assertEqual(_read_pe_exports(SHIM_DLL_SOURCE), _read_pe_exports(official_dll))

        shim_dir = self.tmp / "shim_live"
        shim_dir.mkdir()
        shutil.copy2(SHIM_DLL_SOURCE, shim_dir / "nvngx_dlssg.dll")
        shutil.copy2(MOCK_CORE_DLL, shim_dir / "nvngx_dlssg_core.dll")
        (shim_dir / "si_anr_turbo_dll.ini").write_text(
            "[Turbo]\nEnableBarrierElide=1\nMaxGeneratedCap=2\nCrashShield=1\nHudShield=1\nStrictHudFallback=0\nSceneCutAutoReset=1\nSpikeGuardMs=40\nDiagLog=1\n",
            encoding="utf-8",
        )

        core = ctypes.WinDLL(str(shim_dir / "nvngx_dlssg_core.dll"))
        core.MockCreateParams.restype = ctypes.c_void_p
        core.MockDestroyParams.argtypes = [ctypes.c_void_p]
        core.MockSetUInt.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint]
        core.MockGetUInt.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        core.MockGetUInt.restype = ctypes.c_uint
        core.MockSetFloat.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_float]
        core.MockSetPtr.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]
        core.MockWasBarrierElideSeen.restype = ctypes.c_int

        dut = ctypes.WinDLL(str(shim_dir / "nvngx_dlssg.dll"))
        for fn in ("NVSDK_NGX_D3D12_Init", "NVSDK_NGX_D3D12_CreateFeature", "NVSDK_NGX_D3D12_EvaluateFeature", "NVSDK_NGX_D3D12_ReleaseFeature"):
            getattr(dut, fn).restype = ctypes.c_uint32

        self.assertEqual(dut.NRFG_PresentationControl(None, None), 77)
        self.assertEqual(core.MockWasBarrierElideSeen(), 1)
        self.assertEqual(dut.NVSDK_NGX_D3D12_Init(1, "C:\\Game", ctypes.c_void_p(0x1000), 0x15), 1)

        p = core.MockCreateParams()
        handle = ctypes.c_void_p()
        try:
            self.assertEqual(dut.NVSDK_NGX_D3D12_CreateFeature(None, 11, ctypes.c_void_p(p), ctypes.byref(handle)), 0xBAD00003)
            self.assertEqual(dut.NVSDK_NGX_D3D12_CreateFeature(ctypes.c_void_p(0x2000), 11, ctypes.c_void_p(p), ctypes.byref(handle)), 1)

            for i in range(12):
                core.MockSetUInt(p, b"DLSSG.MultiFrameCount", 5)
                core.MockSetPtr(p, b"DLSSG.HUDLess", ctypes.c_void_p(0x3000))
                core.MockSetFloat(p, b"DLSSG.CameraPosX", float(i))
                core.MockSetFloat(p, b"DLSSG.CameraPosY", 0.0)
                core.MockSetFloat(p, b"DLSSG.CameraPosZ", 0.0)
                core.MockSetFloat(p, b"DLSSG.CameraFOV", 1.2)
                core.MockSetUInt(p, b"DLSSG.Reset", 0)
                core.MockSetUInt(p, b"DLSSG.OutputDisableInterpolation", 0)
                self.assertEqual(dut.NVSDK_NGX_D3D12_EvaluateFeature(ctypes.c_void_p(0x2000), handle, ctypes.c_void_p(p), None), 1)
                self.assertEqual(core.MockGetUInt(p, b"DLSSG.MultiFrameCount"), 2)
                time.sleep(0.008)

            # HUDLess missing triggers UI recomposition shield
            core.MockSetPtr(p, b"DLSSG.HUDLess", None)
            core.MockSetUInt(p, b"DLSSG.UserInterfaceRecompositionEnabled", 0)
            dut.NVSDK_NGX_D3D12_EvaluateFeature(ctypes.c_void_p(0x2000), handle, ctypes.c_void_p(p), None)
            self.assertEqual(core.MockGetUInt(p, b"DLSSG.UserInterfaceRecompositionEnabled"), 1)
            self.assertEqual(core.MockGetUInt(p, b"DLSSG.MultiFrameCount"), 1)

            # Camera teleport injects scene cut reset
            core.MockSetPtr(p, b"DLSSG.HUDLess", ctypes.c_void_p(0x3000))
            core.MockSetFloat(p, b"DLSSG.CameraPosX", 500.0)
            core.MockSetUInt(p, b"DLSSG.Reset", 0)
            dut.NVSDK_NGX_D3D12_EvaluateFeature(ctypes.c_void_p(0x2000), handle, ctypes.c_void_p(p), None)
            self.assertEqual(core.MockGetUInt(p, b"DLSSG.Reset"), 1)

            # Frametime spike injects OutputDisableInterpolation
            time.sleep(0.060)
            core.MockSetUInt(p, b"DLSSG.OutputDisableInterpolation", 0)
            dut.NVSDK_NGX_D3D12_EvaluateFeature(ctypes.c_void_p(0x2000), handle, ctypes.c_void_p(p), None)
            self.assertEqual(core.MockGetUInt(p, b"DLSSG.OutputDisableInterpolation"), 1)

            # VEH Crash Shield catches live 0xC0000005 fault inside EvaluateFeature without crashing
            core.MockSetUInt(p, b"TEST.TriggerFault", 1)
            self.assertEqual(dut.NVSDK_NGX_D3D12_EvaluateFeature(ctypes.c_void_p(0x2000), handle, ctypes.c_void_p(p), None), 1)
            telem = read_live_telemetry()
            self.assertTrue(telem["active"])
            self.assertTrue(telem["fg_bypass_engaged"])
            self.assertGreaterEqual(telem["crashes_blocked"], 2)
        finally:
            core.MockDestroyParams(p)

    def test_system_discovery_smoke(self) -> None:
        gpu = detect_system_gpu()
        self.assertIn("recommended_profile", gpu)
        games = discover_installed_games(extra_dirs=[self.game_dir])
        self.assertTrue(any(g["path"] == str(self.game_dir) for g in games))


if __name__ == "__main__":
    unittest.main(verbosity=2)
