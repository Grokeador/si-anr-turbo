# SI-ANR-Turbo

Open-source **Optimizer, Anti-Cheat Ban Shield & Bug-Fix Patcher** for **[Apex Neural Rendering (ANR FG V.B18)](https://github.com/apex-compute/ANR)** by Apex Compute.

While ANR FG brings cross-GPU AI Frame Generation to NVIDIA RTX/GTX 16, AMD Radeon RX 5000-9000, Steam Deck, and Intel Arc, the stock V.B18 beta package ships with several configuration gaps and open GitHub issues (`#14`, `#17`, `#45`, `#46`, `#50`, `#51`). **SI-ANR-Turbo** fixes them automatically with a Dark Desktop Control Center, Tkinter GUI, CLI, and SHA-256 verified 1-click rollback.

## What SI-ANR-Turbo Fixes

| Fix Module | Stock ANR V.B18 Flaw | SI-ANR-Turbo Mod |
| --- | --- | --- |
| **1. Neural Table Unlocker** (`size_table.json`, `path_table.json`) | Missing `2160p` (4K) for Ada/Blackwell, missing `1080p`/`1440p` for Turing, zero AMD/Intel entries in `size_table.json`, and prediction-only paths on RDNA2/Steam Deck/Arc Alchemist | Unlocks full `1080p`/`1440p`/`2160p` entries across RTX, GTX 16, AMD RDNA2/3/4, Steam Deck, and Intel Arc; prioritizes hardware `vulkan-dp4a` / `portable-xmx` / `coopmat` kernels |
| **2. VRAM Crash & Barrier Elision** (`nr_fg.ini`, `launch_anr_turbo.cmd`) | Defaults to `max_generated = 5` (6X ring buffer), risking GPU MMU freezes on 8-12GB GPUs (Issue #46) | Calibrates `max_generated` safely (`1` for 6-8GB VRAM, `2` for 12-24GB VRAM, saving ~35% buffer memory) and sets `NR_BARRIER_ELIDE=1` compiled inside `nvngx_dlssg.dll` |
| **3. HUD Ghosting & Log Stutter Fix** (`OptiScaler.ini`) | Ships with `LogToFile=true` + `LogLevel=5` (constant disk writes) and HUD/depth flags on `auto` (Issues #14, #17, #50, #51) | Sets `LogToFile=false`, `LogLevel=2`, enables `DrawUIOverFG=true`, `HudlessValidNow=true`, `HUDFix=true`, `HUDFixExtended=true`, `MakeDepthCopy=true`, `MakeMVCopy=true` |
| **4. Flip-Metering Pacing + Ban Shield** (`OptiScaler.ini` + Guard) | Uncalibrated Flip Metering & Reflex state (Issue #45), zero anti-cheat warning before DLL injection | Enables `DisableFlipMetering=false`, `FramePacingTuning=true`, `FPTSafetyMarginInMs=0.25`, `FPTHybridSpin=true`, `ForceReflex=2`; blocks injection if EasyAntiCheat/BattlEye/Vanguard is detected and stores SHA-256 backups |

## Quick Start

```bash
# Launch Desktop App UI
python si_anr_turbo.py web --game-dir "C:\Path\To\Your\Game"

# Launch zero-dependency Tkinter GUI
python si_anr_turbo.py tk --game-dir "C:\Path\To\Your\Game"

# CLI Audit, Apply & Safe Rollback
python si_anr_turbo.py audit --game-dir "C:\Path\To\Your\Game"
python si_anr_turbo.py apply --game-dir "C:\Path\To\Your\Game" --profile rtx_30_20_8gb
python si_anr_turbo.py rollback --game-dir "C:\Path\To\Your\Game"
```

## Automated Tests

```bash
python -m unittest test_turbo.py -v
```
