"""System discovery, GPU/HAGS/VC++ preflight, official ANR GitHub downloader, and live DLL telemetry reader."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import shutil
import subprocess
import urllib.request
import winreg
import zipfile
from pathlib import Path
from typing import Any

ANR_RELEASES_API = "https://api.github.com/repos/apex-compute/ANR/releases/latest"
ANR_FALLBACK_ZIP_URL = "https://github.com/apex-compute/ANR/releases/download/FG-V.B18/anr-fg-V.B18-full.zip"
LOCAL_CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SI-ANR-Turbo" / "cache"
LOCAL_CREATOR_ANR_GAME = Path(r"C:\YOUTUBE\TOOLS\anr-fg-V.B18\game")

VCPP_RUNTIME_DLLS = [
    "msvcp140.dll",
    "msvcp140_1.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
]


class TelemetryStruct(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("magic", ctypes.c_uint32),
        ("version", ctypes.c_uint32),
        ("pid", ctypes.c_uint32),
        ("backend", ctypes.c_uint32),
        ("core_loaded", ctypes.c_uint32),
        ("barrier_elide_active", ctypes.c_uint32),
        ("gpu_vendor", ctypes.c_uint32),
        ("gpu_device", ctypes.c_uint32),
        ("vram_mb", ctypes.c_uint32),
        ("vram_cap_mult", ctypes.c_uint32),
        ("hud_shield_active", ctypes.c_uint32),
        ("spike_guard_active", ctypes.c_uint32),
        ("crash_shield_active", ctypes.c_uint32),
        ("fg_bypass_engaged", ctypes.c_uint32),
        ("eval_count", ctypes.c_uint64),
        ("vram_clamped_frames", ctypes.c_uint64),
        ("hudless_missing_frames", ctypes.c_uint64),
        ("spike_suppressed_frames", ctypes.c_uint64),
        ("scene_cuts_injected", ctypes.c_uint64),
        ("crashes_blocked", ctypes.c_uint64),
        ("last_frame_ms", ctypes.c_float),
        ("avg_frame_ms", ctypes.c_float),
        ("effective_fps", ctypes.c_float),
        ("gpu_name", ctypes.c_char * 128),
    ]


def check_vcpp_runtime() -> list[str]:
    """Return list of missing Microsoft VC++ 2015-2022 Redistributable DLLs."""
    sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    return [dll for dll in VCPP_RUNTIME_DLLS if not (sys32 / dll).exists()]


def check_hags_enabled() -> bool | None:
    """Read Windows Hardware-Accelerated GPU Scheduling state (HwSchMode == 2)."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
        ) as k:
            val, _ = winreg.QueryValueEx(k, "HwSchMode")
            return int(val) == 2
    except OSError:
        return None


def _recommend_profile_from_gpu(name: str, vram_mb: int) -> str:
    low = name.lower()
    if "arc" in low or "intel" in low:
        return "intel_arc_xmx"
    if "radeon" in low or "amd" in low:
        if any(tok in low for tok in ("rx 7", "rx 8", "rx 9", "7900", "7800", "7700", "9070", "9060")):
            return "amd_rdna3_4"
        return "amd_rdna2_deck"
    if "gtx 16" in low or "1650" in low or "1660" in low:
        return "gtx_16_dp4a"
    if vram_mb >= 12000 and any(tok in low for tok in ("rtx 40", "rtx 50", "4070 ti", "4080", "4090", "5070", "5080", "5090")):
        return "rtx_50_40_16gb"
    if any(tok in low for tok in ("rtx 40", "rtx 50")) and vram_mb > 9500:
        return "rtx_50_40_16gb"
    return "rtx_30_20_8gb"


def _read_registry_gpu_vram() -> list[dict[str, Any]]:
    """Read accurate >4GB GPU AdapterDesc & qwMemorySize directly from Windows display class registry."""
    gpus: list[dict[str, Any]] = []
    base_key = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_key) as root:
            for idx in range(16):
                sub = f"{idx:04d}"
                try:
                    with winreg.OpenKey(root, sub) as k:
                        desc, _ = winreg.QueryValueEx(k, "DriverDesc")
                        vram_bytes = 0
                        for val_name in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                            try:
                                raw, _ = winreg.QueryValueEx(k, val_name)
                                if isinstance(raw, bytes) and len(raw) >= 4:
                                    vram_bytes = int.from_bytes(raw[:8].ljust(8, b"\x00"), "little")
                                else:
                                    vram_bytes = int(raw)
                                break
                            except OSError:
                                continue
                        vram_mb = int(vram_bytes // (1024 * 1024)) if vram_bytes > 0 else 0
                        gpus.append({"name": str(desc), "vram_mb": vram_mb})
                except OSError:
                    continue
    except OSError:
        pass
    return gpus


def detect_system_gpu() -> dict[str, Any]:
    """Detect primary discrete GPU, VRAM MB, HAGS status, VC++ status, and recommended profile."""
    gpus = _read_registry_gpu_vram()
    # Filter obvious basic/virtual display adapters when a real GPU is also present
    real_gpus = [
        g for g in gpus
        if not any(skip in g["name"].lower() for skip in ("microsoft basic", "virtual", "parsec", "citrix"))
    ] or gpus

    best = max(real_gpus, key=lambda g: g["vram_mb"]) if real_gpus else {"name": "Unknown GPU (Using Safe 8GB Defaults)", "vram_mb": 8192}
    rec_profile = _recommend_profile_from_gpu(best["name"], best["vram_mb"])
    missing_vcpp = check_vcpp_runtime()
    hags = check_hags_enabled()

    return {
        "name": best["name"],
        "vram_mb": best["vram_mb"],
        "recommended_profile": rec_profile,
        "hags_enabled": hags,
        "missing_vcpp_dlls": missing_vcpp,
        "vcpp_ok": len(missing_vcpp) == 0,
        "all_gpus": real_gpus,
    }


def _find_primary_exe(game_dir: Path) -> str | None:
    """Locate likely main game executable inside root or common Binaries/Win64 folder."""
    skip_words = ("unins", "crash", "report", "redist", "setup", "helper", "launcher", "cleanup")
    candidates: list[Path] = []
    for pat in ("*.exe", "Binaries/Win64/*.exe", "Engine/Binaries/Win64/*.exe"):
        for p in game_dir.glob(pat):
            low = p.name.lower()
            if any(w in low for w in skip_words):
                continue
            candidates.append(p)
    if not candidates:
        candidates = list(game_dir.glob("*.exe"))
    if not candidates:
        return None
    best = max(candidates, key=lambda p: p.stat().st_size if p.exists() else 0)
    return str(best.relative_to(game_dir))


def discover_installed_games(extra_dirs: list[Path] | None = None, limit: int = 40) -> list[dict[str, Any]]:
    """Auto-scan Steam, Epic Games, Xbox/Game Pass, and GOG folders on this PC."""
    found: list[tuple[str, str, Path]] = []
    seen_paths: set[str] = set()

    def _add(source: str, title: str, path: Path) -> None:
        if not path.exists() or not path.is_dir():
            return
        norm = str(path.resolve()).lower()
        if norm in seen_paths:
            return
        seen_paths.add(norm)
        found.append((source, title, path))

    # 1. Steam libraryfolders.vdf
    steam_roots: list[Path] = [Path(r"C:\Program Files (x86)\Steam")]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            sp, _ = winreg.QueryValueEx(k, "SteamPath")
            if sp:
                steam_roots.insert(0, Path(str(sp)))
    except OSError:
        pass

    for sr in steam_roots:
        vdf = sr / "steamapps" / "libraryfolders.vdf"
        lib_paths: list[Path] = [sr / "steamapps"]
        if vdf.exists():
            txt = vdf.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
                p = Path(m.group(1).replace("\\\\", "\\")) / "steamapps"
                if p.exists() and p not in lib_paths:
                    lib_paths.append(p)
        for lp in lib_paths:
            for acf in lp.glob("appmanifest_*.acf"):
                txt = acf.read_text(encoding="utf-8", errors="replace")
                nm = re.search(r'"name"\s+"([^"]+)"', txt)
                id_m = re.search(r'"installdir"\s+"([^"]+)"', txt)
                if nm and id_m:
                    gpath = lp / "common" / id_m.group(1)
                    if "steamworks" in nm.group(1).lower() or "proton" in nm.group(1).lower():
                        continue
                    _add("Steam", nm.group(1), gpath)

    # 2. Epic Games Store manifests
    epic_dir = Path(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests")
    if epic_dir.exists():
        for item in epic_dir.glob("*.item"):
            try:
                data = json.loads(item.read_text(encoding="utf-8", errors="replace"))
                if data.get("DisplayName") and data.get("InstallLocation"):
                    _add("Epic", data["DisplayName"], Path(data["InstallLocation"]))
            except Exception:
                continue

    # 3. Xbox / Game Pass & GOG & extra test dirs
    for root, src in ((Path(r"C:\XboxGames"), "Xbox"), (Path(r"C:\GOG Games"), "GOG")):
        if root.exists():
            for child in root.iterdir():
                if child.is_dir():
                    content = child / "Content"
                    _add(src, child.name, content if content.exists() else child)

    if extra_dirs:
        for ed in extra_dirs:
            _add("Demo/Custom", ed.name, ed)

    results: list[dict[str, Any]] = []
    for src, title, gpath in found[:limit]:
        dlssg_dir = gpath / "OptiScaler" / "custom" / "Apex Neural Rendering FG" / "dlssg"
        has_anr = (dlssg_dir / "nvngx_dlssg.dll").exists()
        has_core = (dlssg_dir / "nvngx_dlssg_core.dll").exists()
        status = "SI-ANR-Turbo v2 Active" if (has_anr and has_core) else ("Stock ANR V.B18" if has_anr else "Ready to Install")
        results.append({
            "source": src,
            "title": title,
            "path": str(gpath),
            "exe": _find_primary_exe(gpath),
            "anr_installed": has_anr,
            "turbo_dll_active": has_anr and has_core,
            "status": status,
        })
    return results


def get_official_anr_download_info() -> dict[str, str]:
    """Query GitHub API for latest ANR FG full zip asset URL, with verified V.B18 fallback."""
    url = ANR_FALLBACK_ZIP_URL
    tag = "FG-V.B18"
    filename = "anr-fg-V.B18-full.zip"
    try:
        req = urllib.request.Request(ANR_RELEASES_API, headers={"User-Agent": "SI-ANR-Turbo/2.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            rel = json.loads(resp.read().decode("utf-8"))
        tag = rel.get("tag_name") or tag
        for asset in rel.get("assets", []):
            nm = asset.get("name", "")
            if nm.endswith("-full.zip") and "optiscaler-source" not in nm:
                url = asset["browser_download_url"]
                filename = nm
                break
    except Exception:
        pass
    return {"tag": tag, "filename": filename, "url": url}


def download_and_install_official_anr(game_dir: Path, force_redownload: bool = False) -> dict[str, Any]:
    """
    Download official apex-compute/ANR release zip into %LOCALAPPDATA%\\SI-ANR-Turbo\\cache
    (or reuse cached copy), detect DX12 vs Vulkan wrapper mode, and install clean ANR files.
    """
    if not game_dir.exists() or not game_dir.is_dir():
        return {"ok": False, "error": f"Game directory does not exist: {game_dir}"}

    LOCAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    info = get_official_anr_download_info()
    zip_path = LOCAL_CACHE_DIR / info["filename"]

    downloaded_now = False
    used_source = "cache"
    if force_redownload or not zip_path.exists() or zip_path.stat().st_size < 1_000_000:
        try:
            req = urllib.request.Request(info["url"], headers={"User-Agent": "SI-ANR-Turbo/2.0"})
            tmp_zip = zip_path.with_suffix(".tmp")
            with urllib.request.urlopen(req, timeout=45) as resp, tmp_zip.open("wb") as out:
                shutil.copyfileobj(resp, out, length=256 * 1024)
            tmp_zip.replace(zip_path)
            downloaded_now = True
            used_source = f"github:{info['tag']}"
        except Exception as exc:
            if not zip_path.exists():
                return {"ok": False, "error": f"Download failed ({exc}) and no cached zip exists."}

    # Inspect archive and extract `game/` tree cleanly (equivalent to official install.ps1)
    is_vulkan_only = (game_dir / "vulkan-1.dll").exists()
    existing_dxgi = (game_dir / "dxgi.dll").exists() and not (game_dir / "OptiScaler").exists()
    loader_name = "winmm.dll" if (is_vulkan_only or existing_dxgi) else "dxgi.dll"

    extracted_files: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        prefix = "game/" if any(n.startswith("game/") for n in names) else ""
        required = [n for n in names if n.startswith(prefix) and not n.endswith("/")]
        if not any("nvngx_dlssg.dll" in n for n in required):
            return {"ok": False, "error": "Downloaded archive missing nvngx_dlssg.dll."}

        for member in required:
            rel_path = member[len(prefix):] if prefix else member
            if not rel_path:
                continue
            if rel_path.lower() == "dxgi.dll":
                rel_path = loader_name
            dst = game_dir / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, dst.open("wb") as out:
                shutil.copyfileobj(src, out)
            extracted_files.append(rel_path)

    return {
        "ok": True,
        "release_tag": info["tag"],
        "archive": str(zip_path),
        "source": used_source,
        "downloaded_now": downloaded_now,
        "loader_dll": loader_name,
        "files_installed": len(extracted_files),
    }


def read_live_telemetry() -> dict[str, Any]:
    """Read live shared-memory telemetry published by our compiled x64 nvngx_dlssg.dll."""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenFileMappingW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
    kernel32.OpenFileMappingW.restype = wt.HANDLE
    kernel32.MapViewOfFile.argtypes = [wt.HANDLE, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_size_t]
    kernel32.MapViewOfFile.restype = ctypes.c_void_p
    kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [wt.HANDLE]

    FILE_MAP_READ = 0x0004
    h_map = kernel32.OpenFileMappingW(FILE_MAP_READ, False, "Local\\SI_ANR_Turbo_Telemetry_v2")
    if not h_map:
        return {"active": False, "status": "STANDBY", "message": "Waiting for a patched game using nvngx_dlssg.dll..."}
    view = None
    try:
        view = kernel32.MapViewOfFile(h_map, FILE_MAP_READ, 0, 0, ctypes.sizeof(TelemetryStruct))
        if not view:
            return {"active": False, "status": "STANDBY"}
        t = TelemetryStruct.from_address(view)
        if t.magic != 0x53494154:
            return {"active": False, "status": "STANDBY"}
        backend_map = {0: "Idle", 1: "DirectX 12", 2: "Vulkan"}
        return {
            "active": True,
            "status": "LIVE",
            "pid": int(t.pid),
            "backend": backend_map.get(int(t.backend), "Active"),
            "core_loaded": bool(t.core_loaded),
            "barrier_elide_active": bool(t.barrier_elide_active),
            "gpu_name": t.gpu_name.decode("utf-8", errors="replace").strip("\x00"),
            "gpu_vendor": f"0x{t.gpu_vendor:04X}",
            "gpu_device": f"0x{t.gpu_device:04X}",
            "vram_mb": int(t.vram_mb),
            "vram_cap_multiplier": f"{int(t.vram_cap_mult) + 1}X",
            "hud_shield_active": bool(t.hud_shield_active),
            "spike_guard_active": bool(t.spike_guard_active),
            "crash_shield_active": bool(t.crash_shield_active),
            "fg_bypass_engaged": bool(t.fg_bypass_engaged),
            "eval_count": int(t.eval_count),
            "vram_clamped_frames": int(t.vram_clamped_frames),
            "hudless_missing_frames": int(t.hudless_missing_frames),
            "spike_suppressed_frames": int(t.spike_suppressed_frames),
            "scene_cuts_injected": int(t.scene_cuts_injected),
            "crashes_blocked": int(t.crashes_blocked),
            "last_frame_ms": round(float(t.last_frame_ms), 2),
            "avg_frame_ms": round(float(t.avg_frame_ms), 2),
            "effective_fps": round(float(t.effective_fps), 1),
        }
    finally:
        if view:
            kernel32.UnmapViewOfFile(view)
        kernel32.CloseHandle(h_map)


def launch_game_directory(game_dir: Path) -> dict[str, Any]:
    """Launch primary game executable inside game_dir with NR_BARRIER_ELIDE=1."""
    rel_exe = _find_primary_exe(game_dir)
    if not rel_exe:
        return {"ok": False, "error": f"No runnable game .exe found in {game_dir}"}
    exe_path = game_dir / rel_exe
    env = dict(os.environ)
    env["NR_BARRIER_ELIDE"] = "1"
    proc = subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent), env=env)
    return {"ok": True, "exe": str(exe_path), "pid": proc.pid}
