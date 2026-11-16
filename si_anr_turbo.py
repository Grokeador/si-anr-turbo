"""
SI-ANR-Turbo v2.0 — Upgraded Native nvngx_dlssg.dll Smart-Shield & 1-Click Installer/Optimizer
Target: Apex Neural Rendering (ANR FG V.B18) — https://github.com/apex-compute/ANR
Repository: https://github.com/Grokeador/si-anr-turbo
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any
from urllib.parse import unquote, urlparse

from turbo_system import (
    ANR_RELEASES_API,
    VCPP_RUNTIME_DLLS,
    check_hags_enabled,
    check_vcpp_runtime,
    detect_system_gpu,
    discover_installed_games,
    download_and_install_official_anr,
    launch_game_directory,
    read_live_telemetry,
)

APP_VERSION = "2.0.0"
APP_ROOT = Path(__file__).resolve().parent
SHIM_DLL_SOURCE = APP_ROOT / "native" / "bin" / "nvngx_dlssg.dll"
DEFAULT_TARGET_DIR = r"C:\YOUTUBE\TOOLS\anr-fg-V.B18\demo_patched_game"

DEFAULT_OPTIONS: dict[str, Any] = {
    "unlock_tables": True,
    "crash_vram_shield": True,
    "hud_log_fix": True,
    "spike_pacing_guard": True,
    "gamepass_vulkan_spoof": False,
}

ANTICHEAT_SIGNATURES: dict[str, str] = {
    "easyanticheat": "EasyAntiCheat (EOS / Kernel Ban Risk)",
    "eac_launcher": "EasyAntiCheat Launcher",
    "battleye": "BattlEye Anti-Cheat (Kernel Ban Risk)",
    "beclient": "BattlEye Client",
    "vgk.sys": "Riot Vanguard (Kernel Anti-Cheat)",
    "vgc.exe": "Riot Vanguard Client",
    "faceit": "FACEIT Anti-Cheat",
    "gameguard": "nProtect GameGuard",
    "xigncode": "XIGNCODE3",
    "ricochet": "COD RICOCHET Driver",
}

GPU_PROFILES: dict[str, dict[str, Any]] = {
    "rtx_30_20_8gb": {
        "label": "NVIDIA RTX 30 / 20 (6-8GB VRAM • 2X Safe)",
        "vendor": "nvidia",
        "path": "coopmat",
        "max_generated": 1,
    },
    "rtx_50_40_16gb": {
        "label": "NVIDIA RTX 40 / 50 (12-24GB • 3X High-FPS)",
        "vendor": "nvidia",
        "path": "coopmat",
        "max_generated": 2,
    },
    "gtx_16_dp4a": {
        "label": "NVIDIA GTX 16 Series (Turing • DP4A INT8)",
        "vendor": "nvidia",
        "path": "dp4a",
        "max_generated": 1,
    },
    "amd_rdna3_4": {
        "label": "AMD Radeon RX 7000 / 9000 (RDNA 3/4 • Linalg)",
        "vendor": "amd",
        "path": "linalg",
        "max_generated": 2,
    },
    "amd_rdna2_deck": {
        "label": "AMD Radeon RX 6000 / Steam Deck (RDNA 2 • DP4A)",
        "vendor": "amd",
        "path": "dp4a",
        "max_generated": 1,
    },
    "intel_arc_xmx": {
        "label": "Intel Arc A / B Series / B390 (XMX Engine)",
        "vendor": "intel",
        "path": "portable-xmx",
        "max_generated": 1,
    },
}


def sha256_file(path: Path) -> str:
    """Compute lowercase SHA-256 digest for a file."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_anr_paths(game_dir: Path) -> dict[str, Path]:
    """Locate ANR FG, OptiScaler, native Smart-Shield DLL, and backup files inside a game directory."""
    anr_dlssg = game_dir / "OptiScaler" / "custom" / "Apex Neural Rendering FG" / "dlssg"
    return {
        "game_dir": game_dir,
        "optiscaler_ini": game_dir / "OptiScaler.ini",
        "anr_dlssg_dir": anr_dlssg,
        "nvngx_dlssg_dll": anr_dlssg / "nvngx_dlssg.dll",
        "nvngx_dlssg_core_dll": anr_dlssg / "nvngx_dlssg_core.dll",
        "dll_shield_ini": anr_dlssg / "si_anr_turbo_dll.ini",
        "dll_shield_log": anr_dlssg / "si_anr_turbo_dll.log",
        "nr_fg_ini": anr_dlssg / "nr_fg.ini",
        "size_table": anr_dlssg / "size_table.json",
        "path_table": anr_dlssg / "path_table.json",
        "backup_dir": game_dir / "OptiScaler" / "si_anr_turbo_backup",
        "backup_manifest": game_dir / "OptiScaler" / "si_anr_turbo_backup" / "manifest.json",
        "launcher_cmd": game_dir / "launch_anr_turbo.cmd",
    }


def scan_anticheat(game_dir: Path, max_depth: int = 3) -> dict[str, Any]:
    """Scan game folder for kernel/usermode Anti-Cheat runtimes before injecting DLLs."""
    if not game_dir.exists() or not game_dir.is_dir():
        return {"ok": False, "error": f"Folder not found: {game_dir}", "safe_to_inject": False, "hits": [], "executables": [], "scanned_files": 0, "missing_vcpp_dlls": check_vcpp_runtime()}

    hits: list[dict[str, str]] = []
    executables: list[str] = []
    scanned_files = 0
    base_parts = len(game_dir.resolve().parts)

    for root, dirs, files in os.walk(game_dir):
        depth = len(Path(root).resolve().parts) - base_parts
        if depth >= max_depth:
            dirs[:] = []
        for d in dirs:
            low_d = d.lower()
            for sig, desc in ANTICHEAT_SIGNATURES.items():
                if sig in low_d:
                    hits.append({"path": str(Path(root, d).relative_to(game_dir)), "engine": desc})
        for f in files:
            scanned_files += 1
            low_f = f.lower()
            if low_f.endswith(".exe") and depth <= 2:
                executables.append(str(Path(root, f).relative_to(game_dir)))
            for sig, desc in ANTICHEAT_SIGNATURES.items():
                if sig in low_f:
                    hits.append({"path": str(Path(root, f).relative_to(game_dir)), "engine": desc})

    dedup: list[dict[str, str]] = []
    seen: set[str] = set()
    for h in hits:
        if h["path"] not in seen:
            seen.add(h["path"])
            dedup.append(h)

    return {
        "ok": True,
        "game_dir": str(game_dir),
        "scanned_files": scanned_files,
        "executables": executables,
        "hits": dedup,
        "safe_to_inject": len(dedup) == 0,
        "missing_vcpp_dlls": check_vcpp_runtime(),
    }


def parse_ini_kv(text: str) -> dict[str, dict[str, str]]:
    """Parse INI sections and key=value pairs while tolerating comments."""
    result: dict[str, dict[str, str]] = {"__root__": {}}
    section = "__root__"
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            result.setdefault(section, {})
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            result.setdefault(section, {})[k.strip()] = v.strip()
    return result


def update_ini_sectioned(text: str, updates: dict[str, dict[str, str]]) -> str:
    """Update INI keys inside sections, preserving existing comments and formatting."""
    lines = text.splitlines()
    out: list[str] = []
    current_section = "__root__"
    applied: dict[str, set[str]] = {sec: set() for sec in updates}

    def _flush_missing(sec: str) -> None:
        if sec in updates:
            for k, val in updates[sec].items():
                if k not in applied[sec]:
                    sep = " = " if sec == "__root__" else "="
                    out.append(f"{k}{sep}{val}")
                    applied[sec].add(k)

    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            _flush_missing(current_section)
            current_section = stripped[1:-1].strip()
            out.append(raw)
            continue

        replaced = False
        if current_section in updates and stripped and not stripped.startswith(";") and not stripped.startswith("#") and "=" in stripped:
            key_part = stripped.split("=", 1)[0].strip()
            if key_part in updates[current_section]:
                sep = " = " if " = " in raw else "="
                out.append(f"{key_part}{sep}{updates[current_section][key_part]}")
                applied[current_section].add(key_part)
                replaced = True
        if not replaced:
            out.append(raw)

    _flush_missing(current_section)
    for sec, kv in updates.items():
        pending = {k: v for k, v in kv.items() if k not in applied[sec]}
        if pending and sec != "__root__":
            out.append(f"\n[{sec}]")
            for k, v in pending.items():
                out.append(f"{k}={v}")

    return "\n".join(out) + "\n"


def _is_shim_installed(paths: dict[str, Path]) -> bool:
    if not SHIM_DLL_SOURCE.exists() or not paths["nvngx_dlssg_dll"].exists() or not paths["nvngx_dlssg_core_dll"].exists():
        return False
    return sha256_file(paths["nvngx_dlssg_dll"]) == sha256_file(SHIM_DLL_SOURCE)


def audit_installation(game_dir: Path) -> dict[str, Any]:
    """Inspect ANR FG V.B18 files and report unpatched issues + native Smart-Shield status."""
    paths = resolve_anr_paths(game_dir)
    issues: list[dict[str, str]] = []

    dll_ok = paths["nvngx_dlssg_dll"].exists()
    dll_size = paths["nvngx_dlssg_dll"].stat().st_size if dll_ok else 0
    core_dll_size = paths["nvngx_dlssg_core_dll"].stat().st_size if paths["nvngx_dlssg_core_dll"].exists() else 0
    shim_active = _is_shim_installed(paths) and paths["dll_shield_ini"].exists()

    nr_fg_kv = parse_ini_kv(paths["nr_fg_ini"].read_text(encoding="utf-8", errors="replace")).get("__root__", {}) if paths["nr_fg_ini"].exists() else {}
    opti_kv = parse_ini_kv(paths["optiscaler_ini"].read_text(encoding="utf-8", errors="replace")) if paths["optiscaler_ini"].exists() else {}
    size_tbl = json.loads(paths["size_table"].read_text(encoding="utf-8")) if paths["size_table"].exists() else {}
    path_tbl = json.loads(paths["path_table"].read_text(encoding="utf-8")) if paths["path_table"].exists() else {}

    # 1. Native Smart-Shield DLL Proxy Status
    if dll_ok and not shim_active:
        issues.append({
            "id": "NATIVE_DLL_SHIELD_MISSING",
            "severity": "HIGH",
            "file": "nvngx_dlssg.dll",
            "title": "Stock ANR DLL Lacks Crash Shield, VRAM Clamp & Spike Guard",
            "detail": "Stock V.B18 nvngx_dlssg.dll has no null/SEH crash guard (#72), no dynamic VRAM MultiFrame clamp (#60), no missing-HUDLess shield (#24), and no camera-cut/spike suppression (#64/#68).",
        })

    # 2. size_table.json completeness
    entries_by_key = {(e.get("vendor"), e.get("architecture")): e for e in size_tbl.get("entries", [])}
    missing_4k_ada = "2160p" not in entries_by_key.get(("nvidia", "ada"), {}).get("large", {})
    missing_4k_bw = "2160p" not in entries_by_key.get(("nvidia", "blackwell"), {}).get("large", {})
    missing_turing_1080 = "1080p" not in entries_by_key.get(("nvidia", "turing"), {}).get("large", {})
    has_amd = any(e.get("vendor") == "amd" for e in size_tbl.get("entries", []))
    has_intel = any(e.get("vendor") == "intel" for e in size_tbl.get("entries", []))

    if size_tbl and (missing_4k_ada or missing_4k_bw or missing_turing_1080 or not has_amd or not has_intel):
        issues.append({
            "id": "SIZE_TABLE_GAPS",
            "severity": "HIGH",
            "file": "size_table.json",
            "title": "Incomplete Neural Program Size Table (Missing 4K / AMD / Intel)",
            "detail": f"Ada 2160p missing={missing_4k_ada}, Blackwell 2160p missing={missing_4k_bw}, Turing 1080p missing={missing_turing_1080}, AMD={has_amd}, Intel={has_intel}.",
        })

    # 3. path_table.json prediction paths + Arc B390 (#22)
    pred_count = sum(
        1
        for entry in path_tbl.get("entries", [])
        if entry.get("vendor") in ("nvidia", "amd", "intel")
        and entry.get("order")
        and entry["order"][0].get("source") == "prediction"
    )
    bm_ids = next((e.get("device_ids", []) for e in path_tbl.get("entries", []) if e.get("vendor") == "intel" and e.get("architecture") == "battlemage"), [])
    missing_b390 = bool(path_tbl) and ("0xb080" not in [str(x).lower() for x in bm_ids])
    if pred_count > 0 or missing_b390:
        issues.append({
            "id": "PATH_TABLE_PREDICTION",
            "severity": "MEDIUM",
            "file": "path_table.json",
            "title": "Uncalibrated Prediction Paths & Missing Arc B390 (#22)",
            "detail": f"{pred_count} GPU architectures start on prediction-only backends; Intel Arc B390 (0x8086:0xb080) missing={missing_b390}.",
        })

    # 4. nr_fg.ini max_generated=5 VRAM freeze risk (Issue #46)
    max_gen = nr_fg_kv.get("max_generated", "5")
    if nr_fg_kv and str(max_gen).strip() == "5":
        issues.append({
            "id": "VRAM_RINGBUFFER_FREEZE",
            "severity": "HIGH",
            "file": "nr_fg.ini",
            "title": "Issue #46 / #60 Risk: max_generated = 5 (6X VRAM Allocation)",
            "detail": "Default max_generated=5 allocates huge 6X ring buffers, causing OutOfMemory / GPU MMU freezes on 8-12GB cards.",
        })

    # 5. OptiScaler LogLevel=5 disk I/O stutter
    log_sec = opti_kv.get("Log", {})
    if opti_kv and (log_sec.get("LogToFile", "").lower() == "true" or str(log_sec.get("LogLevel", "")) == "5"):
        issues.append({
            "id": "TRACE_LOG_STUTTER",
            "severity": "HIGH",
            "file": "OptiScaler.ini",
            "title": "Excessive Disk Trace Logging (LogToFile=true, LogLevel=5)",
            "detail": "Stock V.B18 writes verbose trace logs to disk during gameplay, causing periodic I/O frame-time hitches.",
        })

    # 6. HUD ghosting & DisableUI=auto default trap
    fg_sec = opti_kv.get("FrameGen", {})
    optifg_sec = opti_kv.get("OptiFG", {})
    if opti_kv and (fg_sec.get("DrawUIOverFG", "auto") == "auto" or fg_sec.get("DisableUI", "auto") == "auto" or optifg_sec.get("HUDFix", "auto") == "auto"):
        issues.append({
            "id": "HUD_GHOSTING_EXPOSED",
            "severity": "HIGH",
            "file": "OptiScaler.ini",
            "title": "Issues #14/#17/#50/#51: Unprotected HUD & UI Layers",
            "detail": "DrawUIOverFG and HUDFix are left on 'auto' while DisableUI=auto defaults to 'true', causing HUD smearing.",
        })

    # 7. Frame Pacing & Flip Metering (#45)
    fsrfg_sec = opti_kv.get("FSRFG", {})
    if opti_kv and (fsrfg_sec.get("FramePacingTuning", "auto") == "auto" or opti_kv.get("fakenvapi", {}).get("ForceReflex", "auto") == "auto"):
        issues.append({
            "id": "NO_FLIP_METERING",
            "severity": "MEDIUM",
            "file": "OptiScaler.ini",
            "title": "Issue #45: Uncalibrated Frame Pacing & Reflex Markers",
            "detail": "Flip Metering & ForceReflex remain unconfigured, causing uneven frame delivery.",
        })

    anticheat = scan_anticheat(game_dir)
    anr_present = dll_ok and paths["nr_fg_ini"].exists() and paths["optiscaler_ini"].exists()
    return {
        "ok": anr_present,
        "anr_installed": anr_present,
        "native_shim_active": shim_active,
        "native_shim_available": SHIM_DLL_SOURCE.exists(),
        "game_dir": str(game_dir),
        "dll_found": dll_ok,
        "dll_size_bytes": dll_size,
        "core_dll_size_bytes": core_dll_size,
        "backup_exists": paths["backup_manifest"].exists(),
        "issue_count": len(issues) if anr_present else 0,
        "issues": issues,
        "anticheat": anticheat,
        "current_config": {
            "nr_fg": nr_fg_kv,
            "optiscaler_log": log_sec,
            "optiscaler_framegen": {k: fg_sec.get(k, "auto") for k in ("FGInput", "FGNvngxReplacement", "DrawUIOverFG", "DisableUI", "HudlessValidNow")},
            "optiscaler_pacing": {k: fsrfg_sec.get(k, "auto") for k in ("DisableFlipMetering", "FramePacingTuning", "FPTSafetyMarginInMs", "FPTHybridSpin")},
        },
    }


def create_backup(game_dir: Path) -> dict[str, Any]:
    """Create SHA-256 verified backup of ANR/OptiScaler config, JSON tables, and stock nvngx_dlssg.dll."""
    paths = resolve_anr_paths(game_dir)
    paths["backup_dir"].mkdir(parents=True, exist_ok=True)
    if paths["backup_manifest"].exists():
        manifest = json.loads(paths["backup_manifest"].read_text(encoding="utf-8"))
        # Backfill nvngx_dlssg_dll into an older v1 manifest if stock DLL is still present
        files_map = manifest.setdefault("files", {})
        if "nvngx_dlssg_dll" not in files_map and paths["nvngx_dlssg_dll"].exists():
            src_dll = paths["nvngx_dlssg_core_dll"] if paths["nvngx_dlssg_core_dll"].exists() else paths["nvngx_dlssg_dll"]
            dst = paths["backup_dir"] / "nvngx_dlssg.dll"
            shutil.copy2(src_dll, dst)
            files_map["nvngx_dlssg_dll"] = {
                "original_path": str(paths["nvngx_dlssg_dll"]),
                "backup_file": dst.name,
                "sha256": sha256_file(src_dll),
            }
            paths["backup_manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    targets = ["optiscaler_ini", "nr_fg_ini", "size_table", "path_table", "nvngx_dlssg_dll"]
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "game_dir": str(game_dir),
        "files": {},
    }
    for key in targets:
        src = paths[key]
        if src.exists():
            dst = paths["backup_dir"] / src.name
            shutil.copy2(src, dst)
            manifest["files"][key] = {
                "original_path": str(src),
                "backup_file": dst.name,
                "sha256": sha256_file(src),
            }
    paths["backup_manifest"].write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def install_native_dll_shim(game_dir: Path, options: dict[str, Any] | None = None, profile_key: str = "rtx_30_20_8gb") -> dict[str, Any]:
    """
    Deploy native compiled x64 nvngx_dlssg.dll Smart-Shield proxy and write si_anr_turbo_dll.ini,
    while preserving the untouched official Apex binary as nvngx_dlssg_core.dll.
    """
    if not SHIM_DLL_SOURCE.exists():
        return {"ok": False, "error": f"Compiled native DLL not found at {SHIM_DLL_SOURCE}"}
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    paths = resolve_anr_paths(game_dir)
    if not paths["nvngx_dlssg_dll"].exists():
        return {"ok": False, "error": "nvngx_dlssg.dll missing in target game directory."}

    shim_hash = sha256_file(SHIM_DLL_SOURCE)
    current_hash = sha256_file(paths["nvngx_dlssg_dll"])

    # Move original official Apex DLL to nvngx_dlssg_core.dll if not already preserved
    if current_hash != shim_hash:
        shutil.copy2(paths["nvngx_dlssg_dll"], paths["nvngx_dlssg_core_dll"])
    elif not paths["nvngx_dlssg_core_dll"].exists():
        bak_dll = paths["backup_dir"] / "nvngx_dlssg.dll"
        if bak_dll.exists():
            shutil.copy2(bak_dll, paths["nvngx_dlssg_core_dll"])
        else:
            return {"ok": False, "error": "nvngx_dlssg_core.dll missing and no backup snapshot exists."}

    shutil.copy2(SHIM_DLL_SOURCE, paths["nvngx_dlssg_dll"])

    prof = GPU_PROFILES.get(profile_key, GPU_PROFILES["rtx_30_20_8gb"])
    max_cap = 0 if opts.get("crash_vram_shield", True) else 5
    if opts.get("crash_vram_shield", True) and opts.get("max_generated_override"):
        max_cap = int(opts["max_generated_override"])
    elif opts.get("crash_vram_shield", True) and profile_key != "auto":
        # 0 lets DLL also auto-clamp if actual DXGI VRAM is smaller than user-selected profile
        max_cap = int(prof["max_generated"])

    ini_body = (
        "; Generated automatically by SI-ANR-Turbo v2.0\n"
        "[Turbo]\n"
        f"EnableBarrierElide={1 if opts.get('crash_vram_shield', True) else 0}\n"
        f"MaxGeneratedCap={max_cap}\n"
        f"CrashShield={1 if opts.get('crash_vram_shield', True) else 0}\n"
        f"HudShield={1 if opts.get('hud_log_fix', True) else 0}\n"
        "StrictHudFallback=0\n"
        f"SceneCutAutoReset={1 if opts.get('spike_pacing_guard', True) else 0}\n"
        f"SpikeGuardMs={52 if opts.get('spike_pacing_guard', True) else 0}\n"
        "DiagLog=1\n"
    )
    paths["dll_shield_ini"].write_text(ini_body, encoding="utf-8")
    return {
        "ok": True,
        "shim_bytes": paths["nvngx_dlssg_dll"].stat().st_size,
        "core_bytes": paths["nvngx_dlssg_core_dll"].stat().st_size,
        "max_generated_cap": max_cap,
    }


def rollback_backup(game_dir: Path) -> dict[str, Any]:
    """Restore original SHA-256 verified files (including original nvngx_dlssg.dll) and clean shim files."""
    paths = resolve_anr_paths(game_dir)
    if not paths["backup_manifest"].exists():
        return {"ok": False, "error": "No SI-ANR-Turbo backup manifest found."}
    manifest = json.loads(paths["backup_manifest"].read_text(encoding="utf-8"))
    restored: list[str] = []
    for _, meta in manifest.get("files", {}).items():
        b_file = paths["backup_dir"] / meta["backup_file"]
        orig_path = Path(meta["original_path"])
        if b_file.exists():
            shutil.copy2(b_file, orig_path)
            if sha256_file(orig_path) != meta["sha256"]:
                return {"ok": False, "error": f"SHA-256 verification failed restoring {orig_path.name}"}
            restored.append(orig_path.name)

    for cleanup in (paths["launcher_cmd"], paths["nvngx_dlssg_core_dll"], paths["dll_shield_ini"], paths["dll_shield_log"]):
        if cleanup.exists():
            cleanup.unlink()
    return {"ok": True, "restored": restored}


def patch_neural_tables(game_dir: Path) -> dict[str, Any]:
    """Fix size_table.json gaps and calibrate path_table.json kernel ordering (incl. Arc B390 #22)."""
    paths = resolve_anr_paths(game_dir)
    size_tbl = json.loads(paths["size_table"].read_text(encoding="utf-8"))
    path_tbl = json.loads(paths["path_table"].read_text(encoding="utf-8"))

    full_large = {"1080p": [2, 6], "1440p": [2, 6], "2160p": [2, 6]}
    safe_large = {"1080p": [2, 3], "1440p": [2, 3], "2160p": [2, 2]}
    existing = {(e.get("vendor"), e.get("architecture")): e for e in size_tbl.get("entries", [])}

    for arch in ("blackwell", "ada", "ampere", "ampere-datacenter"):
        key = ("nvidia", arch)
        if key in existing:
            existing[key]["large"] = dict(full_large)
            existing[key]["source"] = "turbo_unlocked"
    if ("nvidia", "turing") in existing:
        existing[("nvidia", "turing")]["large"] = dict(safe_large)
        existing[("nvidia", "turing")]["source"] = "turbo_unlocked"

    extra_entries = [
        {"vendor": "amd", "architecture": "rdna4", "path": "linalg", "large": dict(full_large), "source": "turbo_unlocked"},
        {"vendor": "amd", "architecture": "rdna3", "path": "linalg", "large": dict(full_large), "source": "turbo_unlocked"},
        {"vendor": "amd", "architecture": "rdna3.5-strix", "path": "dp4a", "large": dict(safe_large), "source": "turbo_unlocked"},
        {"vendor": "amd", "architecture": "rdna2", "path": "dp4a", "large": dict(safe_large), "source": "turbo_unlocked"},
        {"vendor": "amd", "architecture": "rdna2-steam-deck", "path": "dp4a", "large": {"1080p": [2, 3], "1440p": [2, 2], "2160p": [2, 2]}, "source": "turbo_unlocked"},
        {"vendor": "amd", "architecture": "rdna1", "path": "portable", "large": dict(safe_large), "source": "turbo_unlocked"},
        {"vendor": "intel", "architecture": "battlemage", "path": "xmx", "large": dict(safe_large), "source": "turbo_unlocked"},
        {"vendor": "intel", "architecture": "alchemist", "path": "xmx", "large": dict(safe_large), "source": "turbo_unlocked"},
    ]
    for item in extra_entries:
        k = (item["vendor"], item["architecture"])
        if k in existing:
            existing[k].update(item)
        else:
            size_tbl["entries"].append(item)

    paths["size_table"].write_text(json.dumps(size_tbl, indent=2), encoding="utf-8")

    tuned_orders: dict[tuple[str, str], list[dict[str, str]]] = {
        ("nvidia", "ampere"): [
            {"path": "vulkan-coopmat", "source": "turbo_calibrated"},
            {"path": "d3d12-linalg", "source": "turbo_calibrated"},
            {"path": "vulkan-packed", "source": "turbo_calibrated"},
            {"path": "vulkan-portable", "source": "turbo_calibrated"},
            {"path": "d3d12-packed", "source": "turbo_calibrated"},
        ],
        ("nvidia", "hopper"): [
            {"path": "vulkan-coopmat", "source": "turbo_calibrated"},
            {"path": "d3d12-linalg", "source": "turbo_calibrated"},
            {"path": "vulkan-packed", "source": "turbo_calibrated"},
        ],
        ("amd", "rdna2"): [
            {"path": "vulkan-dp4a", "source": "turbo_calibrated"},
            {"path": "vulkan-portable-dp4a", "source": "turbo_calibrated"},
            {"path": "d3d12-dp4a", "source": "turbo_calibrated"},
            {"path": "vulkan-packed", "source": "turbo_calibrated"},
            {"path": "vulkan-portable", "source": "turbo_calibrated"},
        ],
        ("amd", "rdna2-steam-deck"): [
            {"path": "vulkan-portable-dp4a", "source": "turbo_calibrated"},
            {"path": "vulkan-dp4a", "source": "turbo_calibrated"},
            {"path": "vulkan-portable", "source": "turbo_calibrated"},
            {"path": "vulkan-packed", "source": "turbo_calibrated"},
        ],
        ("amd", "rdna1-navi10"): [
            {"path": "vulkan-portable", "source": "turbo_calibrated"},
            {"path": "vulkan-packed", "source": "turbo_calibrated"},
            {"path": "d3d12-packed", "source": "turbo_calibrated"},
        ],
        ("amd", "rdna1"): [
            {"path": "vulkan-portable-dp4a", "source": "turbo_calibrated"},
            {"path": "vulkan-portable", "source": "turbo_calibrated"},
            {"path": "vulkan-dp4a", "source": "turbo_calibrated"},
            {"path": "vulkan-packed", "source": "turbo_calibrated"},
        ],
        ("intel", "alchemist"): [
            {"path": "vulkan-portable-xmx", "source": "turbo_calibrated"},
            {"path": "vulkan-portable-xmx8", "source": "turbo_calibrated"},
            {"path": "vulkan-portable-dp4a", "source": "turbo_calibrated"},
            {"path": "d3d12-dp4a", "source": "turbo_calibrated"},
            {"path": "vulkan-coopmat", "source": "turbo_calibrated"},
        ],
    }
    updated_archs: list[str] = []
    for entry in path_tbl.get("entries", []):
        k = (entry.get("vendor"), entry.get("architecture"))
        if k in tuned_orders:
            entry["order"] = tuned_orders[k]
            updated_archs.append(f"{k[0]}/{k[1]}")
        if k == ("intel", "battlemage"):
            ids = entry.setdefault("device_ids", [])
            if "0xb080" not in [str(x).lower() for x in ids]:
                ids.append("0xb080")

    paths["path_table"].write_text(json.dumps(path_tbl, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "size_table_entries": len(size_tbl.get("entries", [])),
        "tuned_path_architectures": updated_archs,
        "arc_b390_added": True,
    }


def patch_vram_and_barrier(game_dir: Path, profile_key: str = "rtx_30_20_8gb") -> dict[str, Any]:
    """Calibrate nr_fg.ini for VRAM safety (#46/#60) and generate NR_BARRIER_ELIDE=1 launcher."""
    paths = resolve_anr_paths(game_dir)
    profile = GPU_PROFILES.get(profile_key, GPU_PROFILES["rtx_30_20_8gb"])
    raw = paths["nr_fg_ini"].read_text(encoding="utf-8", errors="replace")
    patched = update_ini_sectioned(
        raw,
        {
            "__root__": {
                "path": str(profile["path"]),
                "max_generated": str(profile["max_generated"]),
                "scene_cut": "1",
            }
        },
    )
    paths["nr_fg_ini"].write_text(patched, encoding="utf-8")

    exes = sorted(game_dir.glob("*.exe"), key=lambda p: p.stat().st_size, reverse=True)
    exe_name = exes[0].name if exes else "YOUR_GAME_EXE.exe"
    launcher_body = (
        "@echo off\r\n"
        "REM SI-ANR-Turbo Safe Launcher: nvngx_dlssg.dll also sets NR_BARRIER_ELIDE=1 automatically in-process\r\n"
        "set NR_BARRIER_ELIDE=1\r\n"
        f"start \"\" \"%~dp0{exe_name}\" %*\r\n"
    )
    paths["launcher_cmd"].write_text(launcher_body, encoding="utf-8")
    return {
        "ok": True,
        "profile": profile_key,
        "path": profile["path"],
        "max_generated": profile["max_generated"],
        "nr_barrier_elide": True,
        "launcher_cmd": str(paths["launcher_cmd"]),
    }


def patch_hud_and_pacing(game_dir: Path, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Patch OptiScaler.ini safely based on Yes/No toggles (stops LogLevel=5 stutter, fixes DisableUI=auto trap)."""
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    paths = resolve_anr_paths(game_dir)
    raw = paths["optiscaler_ini"].read_text(encoding="utf-8", errors="replace")
    updates: dict[str, dict[str, str]] = {}

    if opts.get("hud_log_fix", True):
        updates["Log"] = {"LogToFile": "false", "LogLevel": "2"}
        updates["FrameGen"] = {
            "DrawUIOverFG": "true",
            "DisableUI": "false",
            "HudlessValidNow": "true",
            "DisableHudless": "false",
            "PreserveSwapChain": "true",
            "SkipResizeBuffers": "true",
        }
        updates["OptiFG"] = {
            "HUDFix": "true",
            "HUDFixUITexture": "true",
            "HUDFixUIUnblend": "true",
            "MakeDepthCopy": "true",
            "MakeMVCopy": "true",
        }

    if opts.get("spike_pacing_guard", True):
        updates["FSRFG"] = {
            "DisableFlipMetering": "false",
            "FramePacingTuning": "true",
            "FPTSafetyMarginInMs": "0.25",
            "FPTVarianceFactor": "0.15",
            "FPTHybridSpin": "true",
        }
        updates["NvApi"] = {"DisableFlipMetering": "false"}
        updates["DLSSG"] = {"UseGamesReflexMarkers": "true"}
        updates["fakenvapi"] = {"UseFakenvapi": "true", "ForceReflex": "2"}

    if opts.get("gamepass_vulkan_spoof", False):
        updates["Spoofing"] = {
            "StreamlineSpoofing": "true",
            "SpoofHAGS": "true",
            "Dxgi": "true",
            "Vulkan": "true",
            "VulkanExtensionSpoofing": "true",
        }

    if updates:
        patched = update_ini_sectioned(raw, updates)
        paths["optiscaler_ini"].write_text(patched, encoding="utf-8")
    return {"ok": True, "sections_patched": list(updates.keys())}


def apply_all_patches(
    game_dir: Path,
    profile_key: str = "rtx_30_20_8gb",
    force: bool = False,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run Anti-Cheat Shield, snapshot SHA-256 backup, deploy native Smart-Shield DLL, and apply selected mods."""
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    scan = scan_anticheat(game_dir)
    if not scan["ok"]:
        return {"ok": False, "error": scan.get("error", "Invalid game directory")}
    if not scan["safe_to_inject"] and not force:
        return {
            "ok": False,
            "blocked_by_anticheat": True,
            "hits": scan["hits"],
            "error": "Anti-Cheat detected! Injection aborted to protect your account from bans.",
        }

    paths = resolve_anr_paths(game_dir)
    if not paths["nvngx_dlssg_dll"].exists():
        return {"ok": False, "needs_official_download": True, "error": "Official ANR V.B18 files not found in this game folder. Click 'Download & Install Official ANR + Mod' first."}

    manifest = create_backup(game_dir)
    tables_res = patch_neural_tables(game_dir) if opts.get("unlock_tables", True) else {"ok": True, "skipped": True}
    vram_res = patch_vram_and_barrier(game_dir, profile_key=profile_key) if opts.get("crash_vram_shield", True) else {"ok": True, "skipped": True}
    hud_res = patch_hud_and_pacing(game_dir, options=opts)
    shim_res = install_native_dll_shim(game_dir, options=opts, profile_key=profile_key)
    post_audit = audit_installation(game_dir)
    return {
        "ok": bool(shim_res.get("ok")),
        "backup_files": list(manifest.get("files", {}).keys()),
        "tables": tables_res,
        "vram_barrier": vram_res,
        "hud_pacing": hud_res,
        "native_dll_shim": shim_res,
        "remaining_issues": post_audit["issue_count"],
    }


def one_click_setup_and_patch(
    game_dir: Path,
    profile_key: str = "rtx_30_20_8gb",
    options: dict[str, Any] | None = None,
    force_download: bool = False,
) -> dict[str, Any]:
    """Full zero-hassle subscriber flow: Anti-Cheat check -> auto-download official ANR if needed -> apply all upgrades + native DLL."""
    scan = scan_anticheat(game_dir)
    if not scan["ok"]:
        return {"ok": False, "error": scan.get("error", "Invalid game directory")}
    if not scan["safe_to_inject"]:
        return {
            "ok": False,
            "blocked_by_anticheat": True,
            "hits": scan["hits"],
            "error": "Anti-Cheat detected! Blocked before touching any files.",
        }

    paths = resolve_anr_paths(game_dir)
    dl_res: dict[str, Any] | None = None
    if force_download or not paths["nvngx_dlssg_dll"].exists() or not paths["optiscaler_ini"].exists():
        dl_res = download_and_install_official_anr(game_dir, force_redownload=force_download)
        if not dl_res.get("ok"):
            return dl_res

    patch_res = apply_all_patches(game_dir, profile_key=profile_key, options=options)
    patch_res["official_install"] = dl_res
    return patch_res


# ---------------------------------------------------------------------------
# Web Desktop App UI (Subscriber-First 3-Step Flow + Live DLL Telemetry)
# ---------------------------------------------------------------------------
WEB_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SI-ANR-Turbo v2.0 — 1-Click AI Frame Gen Upgrader & Smart-Shield DLL</title>
<style>
:root {
  --bg: #070c14; --panel: #0d1624; --card: #121e31; --border: #223554;
  --accent: #00e5a3; --blue: #38bdf8; --amber: #f59e0b; --red: #ef4444;
  --text: #eef4ff; --muted: #8ea5c8;
}
* { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', system-ui, sans-serif; }
body { background: var(--bg); color: var(--text); height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
.topbar {
  height: 60px; background: #0a111d; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between; padding: 0 22px;
}
.brand { display: flex; align-items: center; gap: 12px; font-weight: 800; font-size: 19px; }
.pill { background: rgba(0,229,163,0.14); color: var(--accent); border: 1px solid rgba(0,229,163,0.45); padding: 4px 11px; border-radius: 999px; font-size: 12px; font-weight: 700; }
.pill.blue { background: rgba(56,189,248,0.14); color: var(--blue); border-color: rgba(56,189,248,0.45); }
.pill.warn { background: rgba(245,158,11,0.16); color: #fcd34d; border-color: rgba(245,158,11,0.45); }
.main { display: flex; flex: 1; overflow: hidden; }
.sidebar {
  width: 310px; background: var(--panel); border-right: 1px solid var(--border);
  padding: 16px 14px; display: flex; flex-direction: column; gap: 8px; overflow-y: auto;
}
.nav-btn {
  text-align: left; padding: 13px 14px; border-radius: 10px; border: 1px solid transparent;
  background: transparent; color: var(--muted); font-size: 14.5px; font-weight: 600; cursor: pointer;
  display: flex; justify-content: space-between; align-items: center;
}
.nav-btn.active { background: #16263f; color: #fff; border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
.content { flex: 1; padding: 20px 26px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 18px 20px; }
.card h2 { font-size: 18px; margin-bottom: 8px; color: #fff; display: flex; align-items: center; gap: 10px; }
.sub { font-size: 13.5px; color: var(--muted); margin-bottom: 12px; line-height: 1.45; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.path-bar { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 12px 16px; display: flex; align-items: center; gap: 10px; }
.path-input, select {
  background: #08101c; border: 1px solid #2b4268; color: var(--text);
  padding: 9px 12px; border-radius: 8px; font-size: 13.5px;
}
.path-input { flex: 1; font-family: Consolas, monospace; }
.btn {
  padding: 10px 16px; border-radius: 8px; border: none; font-weight: 700; font-size: 13.5px;
  cursor: pointer; background: var(--accent); color: #041b12;
}
.btn.sec { background: #1c2e4a; color: #dbeafe; border: 1px solid #355280; }
.btn.blue { background: var(--blue); color: #041926; }
.btn.warn { background: var(--amber); color: #1d1202; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.metric-val { font-size: 28px; font-weight: 800; color: var(--accent); margin: 3px 0; }
.metric-lbl { font-size: 11.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.6px; }
.toggle-row {
  display: flex; align-items: center; justify-content: space-between; gap: 14px;
  padding: 11px 14px; background: #0c1524; border: 1px solid #223554; border-radius: 10px; margin-bottom: 8px;
}
.toggle-row input[type="checkbox"] { width: 20px; height: 20px; accent-color: var(--accent); cursor: pointer; }
.issue-row {
  background: #0c1524; border: 1px solid #263959; border-left: 4px solid var(--amber);
  border-radius: 10px; padding: 11px 14px; margin-bottom: 8px;
}
.issue-row.HIGH { border-left-color: var(--red); }
.issue-row.FIXED { border-left-color: var(--accent); }
.tag { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11.5px; font-weight: 700; margin-right: 6px; }
.tag.HIGH { background: rgba(239,68,68,0.2); color: #fca5a5; }
.tag.MEDIUM { background: rgba(245,158,11,0.2); color: #fcd34d; }
.tag.FIXED { background: rgba(0,229,163,0.18); color: var(--accent); }
.game-item {
  display: flex; justify-content: space-between; align-items: center; padding: 10px 13px;
  background: #0b1321; border: 1px solid #1e3150; border-radius: 9px; margin-bottom: 7px; cursor: pointer;
}
.game-item:hover { border-color: var(--blue); }
.toast { padding: 11px 16px; border-radius: 10px; font-size: 13.5px; font-weight: 600; display: none; }
.toast.ok { display: block; background: rgba(0,229,163,0.14); border: 1px solid var(--accent); color: var(--accent); }
.toast.err { display: block; background: rgba(239,68,68,0.16); border: 1px solid var(--red); color: #fca5a5; }
</style>
</head>
<body>
<div class="topbar">
  <div class="brand">
    <span style="color:var(--accent)">&#9889; SI-ANR-TURBO v2.0</span>
    <span class="pill">NATIVE SMART-SHIELD DLL</span>
    <span class="pill blue" id="gpuPill">DETECTING GPU...</span>
  </div>
  <div style="display:flex;gap:10px;align-items:center">
    <span class="pill" id="telemPill">DLL SHIELD: STANDBY</span>
    <span style="color:var(--muted);font-size:12.5px">github.com/Grokeador/si-anr-turbo</span>
  </div>
</div>

<div class="main">
  <div class="sidebar">
    <button class="nav-btn active" onclick="showTab(0)" id="nav0">Step 1: Game & 1-Click Setup <span class="tag FIXED" id="badgeState">AUTO</span></button>
    <button class="nav-btn" onclick="showTab(1)" id="nav1">Step 2: Yes / No Mod Options</button>
    <button class="nav-btn" onclick="showTab(2)" id="nav2">Step 3: Audit & Bug Proof <span class="tag HIGH" id="badgeIssues">0</span></button>
    <button class="nav-btn" onclick="showTab(3)" id="nav3">Bonus: Live DLL Telemetry</button>

    <div style="margin-top:auto;background:#0a1220;border:1px solid #223556;border-radius:12px;padding:13px">
      <div style="font-size:11.5px;color:var(--muted);margin-bottom:6px">DETECTED GPU PROFILE</div>
      <select id="gpuProfile" style="width:100%;margin-bottom:10px">
        <option value="rtx_30_20_8gb">RTX 20/30 (6-8GB Safe • 2X)</option>
        <option value="rtx_50_40_16gb">RTX 40/50 (12-24GB • 3X)</option>
        <option value="gtx_16_dp4a">GTX 16 Series (DP4A INT8)</option>
        <option value="amd_rdna2_deck">AMD RX 6000 / Steam Deck</option>
        <option value="amd_rdna3_4">AMD RX 7000 / 9000 (Linalg)</option>
        <option value="intel_arc_xmx">Intel Arc A / B / B390 (XMX)</option>
      </select>
      <button class="btn" style="width:100%;margin-bottom:8px" onclick="installAndOptimize()">&#9889; 1-Click Install & Optimize</button>
      <button class="btn blue" style="width:100%;margin-bottom:8px" onclick="launchGame()">&#9654; Launch Game Now</button>
      <button class="btn warn" style="width:100%" onclick="rollbackAll()">&#8634; Restore Original Files</button>
    </div>
  </div>

  <div class="content">
    <div class="path-bar">
      <span style="font-size:12.5px;font-weight:700;color:var(--blue)">GAME FOLDER</span>
      <input class="path-input" id="gamePath" value="">
      <button class="btn sec" onclick="pickGameBrowse()">Browse...</button>
      <button class="btn sec" onclick="runAudit()">Re-Scan</button>
    </div>
    <div id="toastBox" class="toast"></div>
    <div id="tabContent"></div>
  </div>
</div>

<script>
let currentTab = 0;
let stateData = null;
let liveTelem = {active: false};
const opts = {
  unlock_tables: true,
  crash_vram_shield: true,
  hud_log_fix: true,
  spike_pacing_guard: true,
  gamepass_vulkan_spoof: false
};

function setToast(msg, ok=true) {
  const b = document.getElementById('toastBox');
  b.textContent = msg;
  b.className = 'toast ' + (ok ? 'ok' : 'err');
}

async function fetchState() {
  const path = encodeURIComponent(document.getElementById('gamePath').value || '');
  const res = await fetch('/api/state?game_dir=' + path);
  stateData = await res.json();
  if (!document.getElementById('gamePath').value) {
    document.getElementById('gamePath').value = stateData.audit.game_dir;
  }
  const sys = stateData.system;
  if (sys && sys.name) {
    const vramTxt = sys.vram_mb ? (' • ' + Math.round(sys.vram_mb / 1024) + 'GB VRAM') : '';
    document.getElementById('gpuPill').textContent = sys.name + vramTxt;
    if (!window._profInitialized && sys.recommended_profile) {
      document.getElementById('gpuProfile').value = sys.recommended_profile;
      window._profInitialized = true;
    }
  }
  const cnt = stateData.audit.issue_count;
  const b = document.getElementById('badgeIssues');
  b.textContent = cnt === 0 ? '0 BUGS' : cnt + ' BUGS';
  b.className = 'tag ' + (cnt === 0 ? 'FIXED' : 'HIGH');
  const st = document.getElementById('badgeState');
  st.textContent = stateData.audit.native_shim_active ? 'SHIELD ON' : (stateData.audit.anr_installed ? 'UPGRADE' : 'READY');
  renderTab();
}

async function pollTelemetry() {
  try {
    const r = await fetch('/api/telemetry');
    liveTelem = await r.json();
    const tp = document.getElementById('telemPill');
    if (liveTelem.active) {
      tp.textContent = 'LIVE ' + liveTelem.backend + ' • ' + liveTelem.effective_fps + ' FPS • BLOCKED ' + liveTelem.crashes_blocked;
      tp.className = 'pill';
    } else {
      tp.textContent = 'DLL SHIELD: STANDBY';
      tp.className = 'pill blue';
    }
    if (currentTab === 3) renderTab();
  } catch (e) {}
}

function showTab(idx) {
  currentTab = idx;
  for (let i = 0; i < 4; i++) document.getElementById('nav' + i).className = 'nav-btn' + (i === idx ? ' active' : '');
  renderTab();
}

function selectGame(path) {
  document.getElementById('gamePath').value = path;
  fetchState();
}

async function pickGameBrowse() {
  const res = await fetch('/api/browse', {method: 'POST'});
  const d = await res.json();
  if (d.path) {
    document.getElementById('gamePath').value = d.path;
    fetchState();
  }
}

async function runAudit() { await fetchState(); }

async function installAndOptimize() {
  setToast('Checking Anti-Cheat, downloading official ANR if needed & deploying native nvngx_dlssg.dll Smart-Shield...', true);
  const path = document.getElementById('gamePath').value;
  const prof = document.getElementById('gpuProfile').value;
  const res = await fetch('/api/oneclick', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({game_dir: path, profile: prof, options: opts})
  });
  const d = await res.json();
  if (d.ok) {
    setToast('Success! Native Smart-Shield nvngx_dlssg.dll + SHA-256 backup + selected mods are now active.', true);
  } else {
    setToast('Blocked / Error: ' + (d.error || 'Unknown error'), false);
  }
  await fetchState();
}

async function launchGame() {
  const path = document.getElementById('gamePath').value;
  const res = await fetch('/api/launch', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({game_dir: path})
  });
  const d = await res.json();
  setToast(d.ok ? ('Launched ' + d.exe + ' (PID ' + d.pid + ') with NR_BARRIER_ELIDE=1') : ('Launch failed: ' + d.error), d.ok);
}

async function rollbackAll() {
  const path = document.getElementById('gamePath').value;
  const res = await fetch('/api/rollback', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({game_dir: path})
  });
  const d = await res.json();
  setToast(d.ok ? ('Restored SHA-256 verified originals: ' + (d.restored || []).join(', ')) : ('Restore note: ' + d.error), d.ok);
  await fetchState();
}

function toggleOpt(key, val) { opts[key] = val; }

function renderTab() {
  if (!stateData) return;
  const a = stateData.audit;
  const sys = stateData.system || {};
  const games = stateData.games || [];
  const el = document.getElementById('tabContent');

  if (currentTab === 0) {
    const gamesHtml = games.length ? games.map(g => `
      <div class="game-item" onclick="selectGame(${JSON.stringify(g.path).replace(/"/g, '&quot;')})">
        <div>
          <strong>${g.title}</strong> <span class="tag MEDIUM">${g.source}</span>
          <div style="font-size:12px;color:var(--muted);font-family:Consolas">${g.path}</div>
        </div>
        <span class="tag ${g.turbo_dll_active ? 'FIXED' : 'MEDIUM'}">${g.status}</span>
      </div>`).join('') : '<div class="sub">No auto-scanned library games matched — use Browse or paste any game folder above.</div>';

    el.innerHTML = `
      <div class="grid-4">
        <div class="card"><div class="metric-lbl">ANR Engine Status</div><div class="metric-val" style="font-size:21px">${a.native_shim_active ? 'TURBO v2.0' : (a.anr_installed ? 'STOCK V.B18' : 'NOT INSTALLED')}</div><div class="metric-lbl">Smart-Shield DLL Check</div></div>
        <div class="card"><div class="metric-lbl">Anti-Cheat Shield</div><div class="metric-val" style="font-size:21px;color:${a.anticheat.safe_to_inject?'var(--accent)':'#f87171'}">${a.anticheat.safe_to_inject ? 'SAFE TO MOD' : 'BLOCKED'}</div><div class="metric-lbl">${a.anticheat.scanned_files} Files Checked</div></div>
        <div class="card"><div class="metric-lbl">VC++ 2015-2022 CRT</div><div class="metric-val" style="font-size:21px;color:${sys.vcpp_ok?'var(--accent)':'#fcd34d'}">${sys.vcpp_ok ? 'ALL READY' : 'MISSING'}</div><div class="metric-lbl">Runtime Prerequisite</div></div>
        <div class="card"><div class="metric-lbl">Windows HAGS</div><div class="metric-val" style="font-size:21px">${sys.hags_enabled === true ? 'ON' : (sys.hags_enabled === false ? 'OFF' : 'UNKNOWN')}</div><div class="metric-lbl">GPU Scheduling Check</div></div>
      </div>
      <div class="card">
        <h2>Step 1: Pick Your Game (Auto-Detected on This PC)</h2>
        <p class="sub">Click any game below — SI-ANR-Turbo verifies Anti-Cheat safety, downloads official ANR FG V.B18 automatically if missing, creates a SHA-256 backup, and upgrades <code>nvngx_dlssg.dll</code> to our Crash-Shielded Smart DLL.</p>
        <div style="max-height:290px;overflow-y:auto">${gamesHtml}</div>
      </div>`;
  } else if (currentTab === 1) {
    const row = (k, title, desc) => `
      <div class="toggle-row">
        <div><strong>${title}</strong><div class="sub" style="margin:2px 0 0">${desc}</div></div>
        <input type="checkbox" ${opts[k] ? 'checked' : ''} onchange="toggleOpt('${k}', this.checked)">
      </div>`;
    el.innerHTML = `
      <div class="card">
        <h2>Step 2: Simple Yes / No Optimization Switches</h2>
        <p class="sub">Choose which upgrades our installer puts inside the game & native <code>nvngx_dlssg.dll</code>. No INI or JSON editing required.</p>
        ${row('unlock_tables', 'Unlock All GPUs & 4K Profiles (RTX / GTX 16 / AMD RX / Steam Deck / Arc B390)', 'Adds missing 4K rows, prioritizes DP4A/XMX hardware paths, and registers Intel Arc B390 (0x8086:0xb080).')}
        ${row('crash_vram_shield', 'Native nvngx_dlssg.dll Crash Shield & 8GB VRAM Cap + NR_BARRIER_ELIDE=1', 'Intercepts null pointers & DX12/Vulkan faults (VEH Crash Shield), caps MultiFrameCount from real DXGI VRAM, and eliminates batch launcher requirement.')}
        ${row('hud_log_fix', 'Stop HUD / Minimap Ghosting & Disk-Log Stutter', 'Disables LogLevel=5 trace disk writes, fixes OptiScaler DisableUI=auto trap, and guards games missing HUDLess buffers.')}
        ${row('spike_pacing_guard', 'Smooth Frame Pacing, Spike Suppressor & Teleport Auto-Reset', 'Detects sudden frametime hitches & camera cuts in-DLL and cleanly pauses interpolation / injects DLSSG.Reset.')}
        ${row('gamepass_vulkan_spoof', 'Xbox Game Pass / Vulkan Spoof Boost (Enable if FG stays greyed out)', 'Forces StreamlineSpoofing=true, SpoofHAGS=true, and Vulkan GPU spoofing.')}
      </div>`;
  } else if (currentTab === 2) {
    const issuesHtml = a.issues.length ? a.issues.map(i => `
      <div class="issue-row ${i.severity}">
        <div><span class="tag ${i.severity}">${i.severity}</span><strong>${i.title}</strong> <span style="color:var(--blue);font-family:Consolas">[${i.file}]</span></div>
        <div style="color:var(--muted);font-size:13px;margin-top:4px">${i.detail}</div>
      </div>`).join('') : `<div class="issue-row FIXED"><span class="tag FIXED">ALL 7 FIXED</span><strong>0 Remaining ANR V.B18 Issues</strong> — Native Smart-Shield nvngx_dlssg.dll + all config fixes are active.</div>`;
    el.innerHTML = `
      <div class="card">
        <h2>Step 3: Pre-Flight Audit & Stock V.B18 Proof (${a.issue_count} Active Issues)</h2>
        <p class="sub">Real-time scan of <code>nvngx_dlssg.dll</code> (${(a.dll_size_bytes/1024).toFixed(0)} KB), <code>nvngx_dlssg_core.dll</code> (${(a.core_dll_size_bytes/1024).toFixed(0)} KB), JSON tables, and <code>OptiScaler.ini</code>.</p>
        ${issuesHtml}
      </div>`;
  } else if (currentTab === 3) {
    const t = liveTelem;
    el.innerHTML = `
      <div class="grid-3">
        <div class="card"><div class="metric-lbl">Stream Status</div><div class="metric-val">${t.active ? t.backend : 'STANDBY'}</div><div class="metric-lbl">${t.active ? ('PID ' + t.pid + ' • ' + t.gpu_name) : 'Launch patched game to monitor'}</div></div>
        <div class="card"><div class="metric-lbl">Live Base Frame Pacing</div><div class="metric-val">${t.active ? (t.effective_fps + ' FPS') : '--'}</div><div class="metric-lbl">${t.active ? (t.avg_frame_ms + ' ms avg • Cap ' + t.vram_cap_multiplier) : 'Telemetry Shared Memory'}</div></div>
        <div class="card"><div class="metric-lbl">Crashes & Spikes Blocked</div><div class="metric-val">${t.active ? (t.crashes_blocked + ' / ' + t.spike_suppressed_frames) : '0 / 0'}</div><div class="metric-lbl">Crash Shield / Spike Guard</div></div>
      </div>
      <div class="card">
        <h2>Bonus: Live Native nvngx_dlssg.dll Shared-Memory Telemetry</h2>
        <p class="sub">Updates live at ~1 Hz whenever any DirectX 12 or Vulkan game loads our upgraded <code>nvngx_dlssg.dll</code>.</p>
        <pre style="background:#070c14;border:1px solid #223554;border-radius:10px;padding:14px;font-family:Consolas,monospace;font-size:13px;color:#cbd5e1">${JSON.stringify(t, null, 2)}</pre>
      </div>`;
  }
}

fetchState();
setInterval(pollTelemetry, 900);
</script>
</body>
</html>
"""


def start_web_server(target_dir: Path, port: int = 8788) -> ThreadingHTTPServer:
    """Create and bind the live SI-ANR-Turbo v2.0 local HTTP control server."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, data: dict[str, Any], code: int = 200) -> None:
            payload = json.dumps(data).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                html = WEB_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
                return

            if parsed.path == "/api/state":
                qs = parsed.query
                gdir = target_dir
                if "game_dir=" in qs:
                    val = unquote(qs.split("game_dir=", 1)[1].split("&", 1)[0]).strip()
                    if val:
                        gdir = Path(val)
                demos = [Path(DEFAULT_TARGET_DIR)] if Path(DEFAULT_TARGET_DIR).exists() else []
                self._send_json({
                    "ok": True,
                    "audit": audit_installation(gdir),
                    "system": detect_system_gpu(),
                    "games": discover_installed_games(extra_dirs=demos),
                })
                return

            if parsed.path == "/api/telemetry":
                self._send_json(read_live_telemetry())
                return

            self.send_error(404)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            body = json.loads(raw.decode("utf-8")) if raw else {}
            gdir = Path(body.get("game_dir") or str(target_dir))
            if self.path == "/api/apply":
                self._send_json(apply_all_patches(gdir, profile_key=body.get("profile", "rtx_30_20_8gb"), options=body.get("options")))
                return
            if self.path == "/api/oneclick":
                self._send_json(one_click_setup_and_patch(gdir, profile_key=body.get("profile", "rtx_30_20_8gb"), options=body.get("options")))
                return
            if self.path == "/api/launch":
                self._send_json(launch_game_directory(gdir))
                return
            if self.path == "/api/rollback":
                self._send_json(rollback_backup(gdir))
                return
            if self.path == "/api/browse":
                picked = ""
                try:
                    tmp_root = tk.Tk()
                    tmp_root.withdraw()
                    tmp_root.attributes("-topmost", True)
                    picked = filedialog.askdirectory(initialdir=str(target_dir))
                    tmp_root.destroy()
                except Exception:
                    picked = ""
                self._send_json({"ok": True, "path": picked})
                return
            self.send_error(404)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


# ---------------------------------------------------------------------------
# Native Desktop Tkinter App (--tk) — 3-Step Gamer Flow + Yes/No Switches
# ---------------------------------------------------------------------------
def launch_tk_gui(initial_dir: Path) -> None:
    """Launch sleek dark-mode native desktop installer & optimizer (no browser required)."""
    sys_info = detect_system_gpu()
    demos = [Path(DEFAULT_TARGET_DIR)] if Path(DEFAULT_TARGET_DIR).exists() else []
    games = discover_installed_games(extra_dirs=demos)

    root = tk.Tk()
    root.title(f"SI-ANR-Turbo v{APP_VERSION} — 1-Click Neural FG Installer & Smart-Shield DLL")
    root.geometry("1040x730")
    root.configure(bg="#070c14")

    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TFrame", background="#070c14")
    style.configure("Card.TFrame", background="#121e31")
    style.configure("TLabel", background="#070c14", foreground="#eef4ff", font=("Segoe UI", 10))
    style.configure("Header.TLabel", font=("Segoe UI", 15, "bold"), foreground="#00e5a3")
    style.configure("Sub.TLabel", font=("Segoe UI", 9), foreground="#8ea5c8")
    style.configure("TCheckbutton", background="#070c14", foreground="#e2ecff", font=("Segoe UI", 10))

    top = ttk.Frame(root, padding=(16, 12))
    top.pack(fill=tk.X)
    ttk.Label(top, text="SI-ANR-Turbo v2.0 — Native nvngx_dlssg.dll Smart-Shield & 1-Click Optimizer", style="Header.TLabel").pack(anchor=tk.W)
    vram_gb = round(sys_info["vram_mb"] / 1024, 1) if sys_info["vram_mb"] else 0
    ttk.Label(
        top,
        text=f"GPU: {sys_info['name']} ({vram_gb} GB VRAM)  |  VC++ Runtime: {'OK' if sys_info['vcpp_ok'] else 'MISSING'}  |  HAGS: {'ON' if sys_info['hags_enabled'] else 'OFF/Auto'}",
        style="Sub.TLabel",
    ).pack(anchor=tk.W, pady=(2, 0))

    # Step 1: Game Picker
    row = ttk.Frame(root, padding=(16, 6))
    row.pack(fill=tk.X)
    ttk.Label(row, text="Step 1 — Game Folder:").pack(side=tk.LEFT, padx=(0, 8))
    dir_var = tk.StringVar(value=str(initial_dir))
    prof_var = tk.StringVar(value=sys_info["recommended_profile"])

    game_choices = [f"[{g['source']}] {g['title']} -> {g['path']}" for g in games]
    combo = ttk.Combobox(row, values=game_choices, width=42, state="readonly")
    if game_choices:
        combo.pack(side=tk.LEFT, padx=(0, 8))

    def _on_pick_game(_evt: Any) -> None:
        sel = combo.get()
        if " -> " in sel:
            dir_var.set(sel.split(" -> ", 1)[1])
            _write(audit_installation(Path(dir_var.get())))

    combo.bind("<<ComboboxSelected>>", _on_pick_game)
    ttk.Entry(row, textvariable=dir_var, width=46).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(row, text="Browse", command=lambda: (p := filedialog.askdirectory(initialdir=dir_var.get())) and dir_var.set(p)).pack(side=tk.LEFT)

    # Step 2: Yes / No Switches
    chk_frame = ttk.Frame(root, padding=(16, 8))
    chk_frame.pack(fill=tk.X)
    ttk.Label(chk_frame, text="Step 2 — Choose Optimizations (Yes / No):", font=("Segoe UI", 10, "bold"), foreground="#38bdf8").pack(anchor=tk.W, pady=(0, 4))
    var_tables = tk.BooleanVar(value=True)
    var_crash = tk.BooleanVar(value=True)
    var_hud = tk.BooleanVar(value=True)
    var_spike = tk.BooleanVar(value=True)
    var_spoof = tk.BooleanVar(value=False)

    ttk.Checkbutton(chk_frame, text="YES: Unlock All GPUs & 4K Tables (RTX 20-50, GTX 16, AMD RX 6000-9000, Steam Deck, Arc B390)", variable=var_tables).pack(anchor=tk.W)
    ttk.Checkbutton(chk_frame, text="YES: Deploy Upgraded nvngx_dlssg.dll (VEH Crash Shield + 8GB VRAM Auto-Cap + NR_BARRIER_ELIDE=1)", variable=var_crash).pack(anchor=tk.W)
    ttk.Checkbutton(chk_frame, text="YES: Fix HUD / Minimap Ghosting & Disable Verbose Trace Disk Log (LogLevel=5)", variable=var_hud).pack(anchor=tk.W)
    ttk.Checkbutton(chk_frame, text="YES: Smooth Frame Pacing, Suppress Choppy Spikes & Teleport Auto-Reset", variable=var_spike).pack(anchor=tk.W)
    ttk.Checkbutton(chk_frame, text="OPTIONAL: Xbox Game Pass / Vulkan Spoof Boost (enable if DLSS FG toggle is hidden)", variable=var_spoof).pack(anchor=tk.W)

    def _current_opts() -> dict[str, Any]:
        return {
            "unlock_tables": bool(var_tables.get()),
            "crash_vram_shield": bool(var_crash.get()),
            "hud_log_fix": bool(var_hud.get()),
            "spike_pacing_guard": bool(var_spike.get()),
            "gamepass_vulkan_spoof": bool(var_spoof.get()),
        }

    log_box = scrolledtext.ScrolledText(root, bg="#0b1322", fg="#cde2ff", font=("Consolas", 10), height=18)
    log_box.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

    def _write(obj: Any) -> None:
        log_box.delete("1.0", tk.END)
        log_box.insert(tk.END, json.dumps(obj, indent=2))

    # Step 3: 1-Click Actions
    btns = ttk.Frame(root, padding=(16, 10))
    btns.pack(fill=tk.X)
    ttk.Combobox(btns, textvariable=prof_var, values=list(GPU_PROFILES.keys()), width=20, state="readonly").pack(side=tk.LEFT, padx=(0, 8))

    def _run_oneclick() -> None:
        res = one_click_setup_and_patch(Path(dir_var.get()), profile_key=prof_var.get(), options=_current_opts())
        _write(res)
        if res.get("ok"):
            messagebox.showinfo("SI-ANR-Turbo v2.0", "Native Smart-Shield DLL & selected optimizations installed successfully!")
        else:
            messagebox.showwarning("SI-ANR-Turbo v2.0", res.get("error", "Operation halted"))

    ttk.Button(btns, text="1. Scan Game", command=lambda: _write(audit_installation(Path(dir_var.get())))).pack(side=tk.LEFT, padx=4)
    ttk.Button(btns, text="2. 1-Click Download + Install & Mod", command=_run_oneclick).pack(side=tk.LEFT, padx=4)
    ttk.Button(btns, text="3. Launch Game", command=lambda: _write(launch_game_directory(Path(dir_var.get())))).pack(side=tk.LEFT, padx=4)
    ttk.Button(btns, text="4. Restore Backup", command=lambda: _write(rollback_backup(Path(dir_var.get())))).pack(side=tk.LEFT, padx=4)

    _write({"audit": audit_installation(initial_dir), "live_telemetry": read_live_telemetry()})
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="SI-ANR-Turbo v2.0: Native nvngx_dlssg.dll Smart-Shield & 1-Click Optimizer")
    parser.add_argument("command", nargs="?", default="web", choices=["web", "tk", "audit", "apply", "oneclick", "rollback", "scan", "telemetry", "discover"])
    parser.add_argument("--game-dir", default=DEFAULT_TARGET_DIR, help="Path to game .exe folder")
    parser.add_argument("--profile", default="rtx_30_20_8gb", choices=list(GPU_PROFILES.keys()))
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--force", action="store_true", help="Override Anti-Cheat gate (NOT recommended)")
    parser.add_argument("--spoof", action="store_true", help="Enable Game Pass / Vulkan spoofing boost")
    args = parser.parse_args()

    target = Path(args.game_dir)
    opts = dict(DEFAULT_OPTIONS)
    if args.spoof:
        opts["gamepass_vulkan_spoof"] = True

    if args.command == "audit":
        print(json.dumps(audit_installation(target), indent=2))
    elif args.command == "scan":
        print(json.dumps(scan_anticheat(target), indent=2))
    elif args.command == "telemetry":
        print(json.dumps(read_live_telemetry(), indent=2))
    elif args.command == "discover":
        print(json.dumps({"system": detect_system_gpu(), "games": discover_installed_games()}, indent=2))
    elif args.command == "apply":
        res = apply_all_patches(target, profile_key=args.profile, force=args.force, options=opts)
        print(json.dumps(res, indent=2))
        if not res.get("ok"):
            sys.exit(1)
    elif args.command == "oneclick":
        res = one_click_setup_and_patch(target, profile_key=args.profile, options=opts)
        print(json.dumps(res, indent=2))
        if not res.get("ok"):
            sys.exit(1)
    elif args.command == "rollback":
        res = rollback_backup(target)
        print(json.dumps(res, indent=2))
        if not res.get("ok"):
            sys.exit(1)
    elif args.command == "tk":
        launch_tk_gui(target)
    elif args.command == "web":
        srv = start_web_server(target, port=args.port)
        url = f"http://127.0.0.1:{args.port}/"
        print(f"SI-ANR-Turbo v{APP_VERSION} Control Center live at {url}", flush=True)
        for browser in (
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        ):
            if os.path.exists(browser):
                threading.Thread(target=lambda b=browser: subprocess.Popen([b, f"--app={url}"]), daemon=True).start()
                break
        srv.serve_forever()


if __name__ == "__main__":
    main()
