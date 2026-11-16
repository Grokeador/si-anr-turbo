# SI-ANR-Turbo v2.0

Open-source **Native `nvngx_dlssg.dll` Smart-Shield Upgrade & 1-Click Installer** for **[Apex Neural Rendering (ANR FG V.B18)](https://github.com/apex-compute/ANR)** by Apex Compute.

Unlike simple INI editors, **SI-ANR-Turbo v2.0** compiles and deploys a real **native x64 C proxy DLL (`nvngx_dlssg.dll` -> `nvngx_dlssg_core.dll`)** alongside a zero-jargon 1-Click Desktop App that automatically scans your Steam/Epic/Xbox/GOG games, downloads official ANR V.B18 from GitHub, verifies Anti-Cheat safety & VC++ runtimes, backs up everything with SHA-256, and lets you toggle fixes with simple Yes/No switches.

## What Our Upgraded Native `nvngx_dlssg.dll` Adds Inside the Game Process

1. **Pre-Load `NR_BARRIER_ELIDE=1` Injection** — Automatically sets `NR_BARRIER_ELIDE=1` inside the game process before loading `nvngx_dlssg_core.dll`, so launching directly from **Steam, Epic, or Xbox Game Pass** keeps barrier elision active with no batch script required.
2. **Live DXGI VRAM Detection & `MultiFrameCount` Clamp (Issues `#46`, `#60`)** — Queries the active hardware GPU via `IDXGIFactory1` and caps `DLSSG.MultiFrameCount` safely (`2X` on <=8GB GPUs, `3X` on 10-12GB GPUs, `5X` on 16GB+), preventing `0x8007000E` `CreateComputePipelineState` out-of-memory errors and GPU MMU freezes.
3. **Null Parameter Guard & VEH Crash Shield (Issues `#40`, `#58`, `#72`)** — Validates `CmdList`, `FeatureHandle`, and `InParameters` before calling Apex's core binary and wraps `CreateFeature` / `EvaluateFeature` in a thread-local Vectored Exception Handler that cleanly switches to passthrough instead of crashing to desktop on `0xC0000005`.
4. **Missing HUDLess / UI Buffer Shield (Issue `#24`)** — Detects frames where the game supplies neither `DLSSG.HUDLess` nor `DLSSG.UI` / `DLSSG.UIAlpha`, enables `DLSSG.UserInterfaceRecompositionEnabled`, and protects minimaps/crosshairs from multi-frame warping.
5. **Frametime Spike & Camera-Teleport Scene-Cut Guard (Issues `#64`, `#68`)** — Tracks per-frame QPC delta timing and camera position/FOV jumps; pauses interpolation (`DLSSG.OutputDisableInterpolation`) during shader/respawn hitches and injects `DLSSG.Reset` on sudden camera cuts.
6. **Live Shared-Memory Telemetry (`Local\SI_ANR_Turbo_Telemetry_v2`)** — Streams real-time base FPS, active DX12/Vulkan backend, detected GPU/VRAM, clamped frames, spike suppressions, and blocked faults straight to the SI-ANR-Turbo UI.

## What Our 1-Click Installer & Tables Fix (`size_table.json`, `path_table.json`, `nr_fg.ini`, `OptiScaler.ini`)

- **Auto-Download & Vulkan/DX12 Detection**: Fetches official `anr-fg-V.B18-full.zip` from `apex-compute/ANR`, installs `dxgi.dll` or `winmm.dll` automatically based on game engine, and stores SHA-256 backups.
- **Anti-Cheat Ban Shield**: Scans for EasyAntiCheat, BattlEye, Vanguard, FACEIT, GameGuard, XIGNCODE, and RICOCHET before touching any file.
- **Full GPU & 4K Unlocker**: Unlocks 4K (`2160p`) on Ada/Blackwell, 1080p/1440p on Turing, adds AMD RDNA1–4 / Steam Deck + Intel Arc tables, and registers **Intel Arc B390 (`0x8086:0xb080`, Issue `#22`)**.
- **HUD & Flip-Metering Fixes (Issues `#14`, `#17`, `#45`, `#50`, `#51`)**: Disables `LogLevel=5` disk trace I/O stutter, fixes `DisableUI=auto` (`DisableUI=false`, `DrawUIOverFG=true`, `PreserveSwapChain=true`, `SkipResizeBuffers=true`), configures `FramePacingTuning` + `ForceReflex=2`, and offers an optional **Xbox Game Pass / Vulkan Spoof Boost (Issue `#15`, `#55`)**.

## Quick Start

Double-click **`Launch_SI_ANR_Turbo.bat`** or run:

```powershell
# Launch 1-Click Dark Desktop App
python si_anr_turbo.py web

# Launch Native Tkinter Window (no browser needed)
python si_anr_turbo.py tk

# 1-Click CLI Download + Install + Upgrade
python si_anr_turbo.py oneclick --game-dir "C:\Path\To\Your\Game"

# Verify & Restore Original Files (SHA-256 Verified)
python si_anr_turbo.py rollback --game-dir "C:\Path\To\Your\Game"
```

## Rebuild Native DLL from Source

Requires Zig 0.17+ (`winget install zig.zig`):

```powershell
python native/build_dll.py
python -m unittest test_turbo.py -v
```
