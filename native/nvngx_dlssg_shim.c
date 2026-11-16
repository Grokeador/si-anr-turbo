/*
 * SI-ANR-Turbo v2.0 — Native x64 Smart-Shield & Frame-Pacing Proxy for nvngx_dlssg.dll
 *
 * Placed at: OptiScaler\custom\Apex Neural Rendering FG\dlssg\nvngx_dlssg.dll
 * Forwards to: OptiScaler\custom\Apex Neural Rendering FG\dlssg\nvngx_dlssg_core.dll
 *
 * Real In-Process Improvements over Stock ANR V.B18:
 *   1. Auto-sets NR_BARRIER_ELIDE=1 before loading nvngx_dlssg_core.dll (works even when launched from Steam/Xbox).
 *   2. Live DXGI Hardware Adapter & VRAM detection -> auto-clamps DLSSG.MultiFrameCount to safe VRAM bounds
 *      (prevents Issue #60 CreateComputePipelineState OOM and Issue #46 8-12GB GPU MMU freezes).
 *   3. Pre-call NGX parameter/handle/cmdlist validation + TLS-scoped VEH Crash Shield
 *      (prevents Issue #72 / #58 / #40 startup and toggle crashes).
 *   4. Missing HUDLess / UI buffer detector & UserInterfaceRecomposition guard (Issue #24).
 *   5. High-resolution QPC frame-time spike & camera-teleport scene-cut guard
 *      (injects OutputDisableInterpolation on hitches [Issue #64] & DLSSG.Reset on camera cuts [Issue #68]).
 *   6. Lock-free shared-memory telemetry ("Local\\SI_ANR_Turbo_Telemetry_v2") read live by SI-ANR-Turbo UI.
 */

#define WIN32_LEAN_AND_MEAN
#define COBJMACROS
#include <windows.h>
#include <dxgi.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <setjmp.h>

#define NVSDK_NGX_Result uint32_t
#define NVSDK_NGX_RESULT_SUCCESS           0x00000001u
#define NVSDK_NGX_RESULT_FAIL_INVALID_PARAM 0xBAD00003u
#define NVSDK_NGX_RESULT_FAIL_NOT_INIT     0xBAD00002u

/* Verified binary MSVC vtable layout of NVSDK_NGX_Parameter observed inside ANR V.B18 nvngx_dlssg.dll */
typedef struct NGX_Param_Vtbl {
    void     (WINAPI *Set_VoidPtr)(void* self, const char* name, void* val);             /* 0x00 */
    void     (WINAPI *Set_D3D12)(void* self, const char* name, void* val);               /* 0x08 */
    void     (WINAPI *Set_D3D11)(void* self, const char* name, void* val);               /* 0x10 */
    void     (WINAPI *Set_Int)(void* self, const char* name, int val);                   /* 0x18 */
    void     (WINAPI *Set_UInt)(void* self, const char* name, unsigned int val);         /* 0x20 */
    void     (WINAPI *Set_Double)(void* self, const char* name, double val);             /* 0x28 */
    void     (WINAPI *Set_Float)(void* self, const char* name, float val);               /* 0x30 */
    void     (WINAPI *Set_ULL)(void* self, const char* name, unsigned long long val);    /* 0x38 */
    uint32_t (WINAPI *Get_VoidPtr)(void* self, const char* name, void** out);            /* 0x40 */
    uint32_t (WINAPI *Get_D3D12)(void* self, const char* name, void** out);              /* 0x48 */
    uint32_t (WINAPI *Get_D3D11)(void* self, const char* name, void** out);              /* 0x50 */
    uint32_t (WINAPI *Get_Int)(void* self, const char* name, int* out);                  /* 0x58 */
    uint32_t (WINAPI *Get_UInt)(void* self, const char* name, unsigned int* out);        /* 0x60 */
    uint32_t (WINAPI *Get_Double)(void* self, const char* name, double* out);            /* 0x68 */
    uint32_t (WINAPI *Get_Float)(void* self, const char* name, float* out);              /* 0x70 */
    uint32_t (WINAPI *Get_ULL)(void* self, const char* name, unsigned long long* out);   /* 0x78 */
    void     (WINAPI *Reset)(void* self);                                                /* 0x80 */
} NGX_Param_Vtbl;

typedef struct NGX_Param_Obj {
    NGX_Param_Vtbl* vtbl;
} NGX_Param_Obj;

#pragma pack(push, 1)
typedef struct SI_ANR_Telemetry_v2 {
    uint32_t magic;                  /* 0x53494154 ('SIAT') */
    uint32_t version;                /* 2 */
    uint32_t pid;
    uint32_t backend;                /* 0=Idle, 1=D3D12, 2=Vulkan */
    uint32_t core_loaded;            /* 1 if nvngx_dlssg_core.dll loaded */
    uint32_t barrier_elide_active;   /* 1 if NR_BARRIER_ELIDE=1 set */
    uint32_t gpu_vendor;
    uint32_t gpu_device;
    uint32_t vram_mb;
    uint32_t vram_cap_mult;          /* Max MultiFrameCount allowed (1=2X..5=6X) */
    uint32_t hud_shield_active;
    uint32_t spike_guard_active;
    uint32_t crash_shield_active;
    uint32_t fg_bypass_engaged;      /* 1 if fault recovery fell back to passthrough */
    uint64_t eval_count;
    uint64_t vram_clamped_frames;
    uint64_t hudless_missing_frames;
    uint64_t spike_suppressed_frames;
    uint64_t scene_cuts_injected;
    uint64_t crashes_blocked;
    float    last_frame_ms;
    float    avg_frame_ms;
    float    effective_fps;
    char     gpu_name[128];
} SI_ANR_Telemetry_v2;
#pragma pack(pop)

/* Runtime INI Settings */
typedef struct TurboConfig {
    int   enable_barrier_elide;
    int   max_generated_cap;   /* 0 = auto from VRAM */
    int   crash_shield;
    int   hud_shield;
    int   strict_hud_fallback;
    int   scene_cut_auto_reset;
    int   diag_log;
    float spike_guard_ms;      /* 0 = disabled, default 52.0f */
} TurboConfig;

/* Core function typedefs */
typedef int              (__cdecl   *PFN_NRFG_PresentationControl)(void* a, void* b);
typedef NVSDK_NGX_Result (WINAPI    *PFN_D3D12_Init)(unsigned long long, const wchar_t*, void*, uint32_t);
typedef NVSDK_NGX_Result (WINAPI    *PFN_D3D12_Init_Ext)(unsigned long long, const wchar_t*, void*, uint32_t, const void*);
typedef NVSDK_NGX_Result (WINAPI    *PFN_Shutdown)(void);
typedef NVSDK_NGX_Result (WINAPI    *PFN_Shutdown1)(void*);
typedef NVSDK_NGX_Result (WINAPI    *PFN_GetScratch)(uint32_t, const void*, size_t*);
typedef NVSDK_NGX_Result (WINAPI    *PFN_D3D12_GetReqs)(void*, const void*, void*);
typedef NVSDK_NGX_Result (WINAPI    *PFN_Populate)(void*);
typedef NVSDK_NGX_Result (WINAPI    *PFN_CreateFeature)(void*, uint32_t, void*, void**);
typedef NVSDK_NGX_Result (WINAPI    *PFN_ReleaseFeature)(void*);
typedef NVSDK_NGX_Result (WINAPI    *PFN_EvaluateFeature)(void*, const void*, const void*, void*);
typedef NVSDK_NGX_Result (WINAPI    *PFN_VK_Init)(unsigned long long, const wchar_t*, void*, void*, void*, void*, void*, const void*, uint32_t);
typedef NVSDK_NGX_Result (WINAPI    *PFN_VK_Init_Ext)(unsigned long long, const wchar_t*, void*, void*, void*, uint32_t, const void*);
typedef NVSDK_NGX_Result (WINAPI    *PFN_VK_Init_Ext2)(unsigned long long, const wchar_t*, void*, void*, void*, void*, void*, uint32_t, const void*);
typedef NVSDK_NGX_Result (WINAPI    *PFN_VK_CreateFeature1)(void*, void*, uint32_t, void*, void**);
typedef NVSDK_NGX_Result (WINAPI    *PFN_VK_GetReqs)(const void*, const void*, const void*, void*);

typedef struct CoreApi {
    PFN_NRFG_PresentationControl NRFG_PresentationControl;
    PFN_CreateFeature            D3D12_CreateFeature;
    PFN_EvaluateFeature          D3D12_EvaluateFeature;
    PFN_D3D12_GetReqs            D3D12_GetFeatureRequirements;
    PFN_GetScratch               D3D12_GetScratchBufferSize;
    PFN_D3D12_Init               D3D12_Init;
    PFN_D3D12_Init_Ext           D3D12_Init_Ext;
    PFN_Populate                 D3D12_PopulateParameters_Impl;
    PFN_ReleaseFeature           D3D12_ReleaseFeature;
    PFN_Shutdown                 D3D12_Shutdown;
    PFN_Shutdown1                D3D12_Shutdown1;
    PFN_CreateFeature            VK_CreateFeature;
    PFN_VK_CreateFeature1        VK_CreateFeature1;
    PFN_EvaluateFeature          VK_EvaluateFeature;
    PFN_VK_GetReqs               VK_GetFeatureRequirements;
    PFN_GetScratch               VK_GetScratchBufferSize;
    PFN_VK_Init                  VK_Init;
    PFN_VK_Init_Ext              VK_Init_Ext;
    PFN_VK_Init_Ext2             VK_Init_Ext2;
    PFN_Populate                 VK_PopulateParameters_Impl;
    PFN_ReleaseFeature           VK_ReleaseFeature;
    PFN_Shutdown                 VK_Shutdown;
    PFN_Shutdown1                VK_Shutdown1;
} CoreApi;

static HINSTANCE            g_self_inst = NULL;
static HMODULE              g_core_mod = NULL;
static CoreApi              g_core;
static SRWLOCK              g_init_lock = SRWLOCK_INIT;
static SRWLOCK              g_log_lock = SRWLOCK_INIT;
static volatile LONG        g_init_done = 0;
static volatile LONG        g_fg_bypass = 0;
static PVOID                g_veh_handle = NULL;
static HANDLE               g_shm_handle = NULL;
static SI_ANR_Telemetry_v2* g_telem = NULL;
static SI_ANR_Telemetry_v2  g_telem_fallback;
static wchar_t              g_dll_dir[MAX_PATH] = {0};
static TurboConfig          g_cfg = {1, 0, 1, 1, 0, 1, 1, 52.0f};

/* Per-frame optical-flow stabilization state */
static CRITICAL_SECTION     g_eval_cs;
static LONG                 g_eval_cs_ready = 0;
static LARGE_INTEGER        g_qpc_freq = {0};
static LARGE_INTEGER        g_last_qpc = {0};
static double               g_ema_ms = 16.67;
static int                  g_spike_cooldown = 0;
static int                  g_have_cam = 0;
static float                g_prev_cam[3] = {0.0f, 0.0f, 0.0f};
static float                g_prev_fov = 0.0f;

/* Thread-local guard for Crash Shield */
typedef struct ShieldTls {
    int     active;
    DWORD   exception_code;
    void*   exception_addr;
    jmp_buf env;
} ShieldTls;

static DWORD g_tls_idx = TLS_OUT_OF_INDEXES;

static ShieldTls* GetShieldTls(void) {
    if (g_tls_idx == TLS_OUT_OF_INDEXES) return NULL;
    ShieldTls* st = (ShieldTls*)TlsGetValue(g_tls_idx);
    if (!st) {
        st = (ShieldTls*)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(ShieldTls));
        if (st) TlsSetValue(g_tls_idx, st);
    }
    return st;
}

static void TurboLog(const char* fmt, ...) {
    if (!g_cfg.diag_log) return;
    wchar_t logPath[MAX_PATH];
    if (!g_dll_dir[0]) return;
    _snwprintf(logPath, MAX_PATH - 1, L"%ls\\si_anr_turbo_dll.log", g_dll_dir);
    logPath[MAX_PATH - 1] = L'\0';

    char buf[512];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf) - 1, fmt, args);
    va_end(args);
    buf[sizeof(buf) - 1] = '\0';

    SYSTEMTIME st;
    GetLocalTime(&st);
    AcquireSRWLockExclusive(&g_log_lock);
    HANDLE h = CreateFileW(logPath, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h != INVALID_HANDLE_VALUE) {
        char line[600];
        int n = snprintf(line, sizeof(line), "[%02d:%02d:%02d.%03d][PID %lu] %s\r\n",
                         st.wHour, st.wMinute, st.wSecond, st.wMilliseconds,
                         (unsigned long)GetCurrentProcessId(), buf);
        if (n > 0) {
            DWORD written = 0;
            WriteFile(h, line, (DWORD)n, &written, NULL);
        }
        CloseHandle(h);
    }
    ReleaseSRWLockExclusive(&g_log_lock);
}

static LONG CALLBACK TurboVehHandler(PEXCEPTION_POINTERS ep) {
    if (!g_cfg.crash_shield || !ep || !ep->ExceptionRecord) return EXCEPTION_CONTINUE_SEARCH;
    DWORD code = ep->ExceptionRecord->ExceptionCode;
    if (code != EXCEPTION_ACCESS_VIOLATION &&
        code != EXCEPTION_ILLEGAL_INSTRUCTION &&
        code != EXCEPTION_FLT_DIVIDE_BY_ZERO &&
        code != EXCEPTION_INT_DIVIDE_BY_ZERO &&
        code != EXCEPTION_STACK_OVERFLOW) {
        return EXCEPTION_CONTINUE_SEARCH;
    }
    if (g_tls_idx == TLS_OUT_OF_INDEXES) return EXCEPTION_CONTINUE_SEARCH;
    ShieldTls* st = (ShieldTls*)TlsGetValue(g_tls_idx);
    if (st && st->active) {
        st->active = 0;
        st->exception_code = code;
        st->exception_addr = ep->ExceptionRecord->ExceptionAddress;
        longjmp(st->env, 1);
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

static int IsReadablePtr(const void* ptr, size_t bytes) {
    if (!ptr || (uintptr_t)ptr < 0x10000u) return 0;
    MEMORY_BASIC_INFORMATION mbi;
    if (VirtualQuery(ptr, &mbi, sizeof(mbi)) == 0) return 0;
    if (mbi.State != MEM_COMMIT) return 0;
    DWORD prot = mbi.Protect & 0xFFu;
    if (prot == PAGE_NOACCESS || prot == PAGE_EXECUTE) return 0;
    uintptr_t end = (uintptr_t)mbi.BaseAddress + mbi.RegionSize;
    return ((uintptr_t)ptr + bytes <= end);
}

static NGX_Param_Obj* SafeAsParam(const void* raw) {
    if (!IsReadablePtr(raw, sizeof(void*))) return NULL;
    NGX_Param_Obj* obj = (NGX_Param_Obj*)(uintptr_t)raw;
    if (!IsReadablePtr(obj->vtbl, sizeof(NGX_Param_Vtbl))) return NULL;
    return obj;
}

static void LoadTurboIni(void) {
    wchar_t iniPath[MAX_PATH];
    _snwprintf(iniPath, MAX_PATH - 1, L"%ls\\si_anr_turbo_dll.ini", g_dll_dir);
    iniPath[MAX_PATH - 1] = L'\0';

    g_cfg.enable_barrier_elide = (int)GetPrivateProfileIntW(L"Turbo", L"EnableBarrierElide", 1, iniPath);
    g_cfg.max_generated_cap    = (int)GetPrivateProfileIntW(L"Turbo", L"MaxGeneratedCap", 0, iniPath);
    g_cfg.crash_shield         = (int)GetPrivateProfileIntW(L"Turbo", L"CrashShield", 1, iniPath);
    g_cfg.hud_shield           = (int)GetPrivateProfileIntW(L"Turbo", L"HudShield", 1, iniPath);
    g_cfg.strict_hud_fallback  = (int)GetPrivateProfileIntW(L"Turbo", L"StrictHudFallback", 0, iniPath);
    g_cfg.scene_cut_auto_reset = (int)GetPrivateProfileIntW(L"Turbo", L"SceneCutAutoReset", 1, iniPath);
    g_cfg.diag_log             = (int)GetPrivateProfileIntW(L"Turbo", L"DiagLog", 1, iniPath);
    int spike_int              = (int)GetPrivateProfileIntW(L"Turbo", L"SpikeGuardMs", 52, iniPath);
    g_cfg.spike_guard_ms       = (spike_int > 0) ? (float)spike_int : 0.0f;
}

typedef HRESULT (WINAPI *PFN_CreateDXGIFactory1)(REFIID riid, void** ppFactory);

static void DetectPrimaryGpuAndComputeCap(SI_ANR_Telemetry_v2* telem) {
    telem->gpu_vendor = 0;
    telem->gpu_device = 0;
    telem->vram_mb = 0;
    snprintf(telem->gpu_name, sizeof(telem->gpu_name), "Unknown Adapter");

    HMODULE hDxgi = LoadLibraryA("dxgi.dll");
    if (hDxgi) {
        PFN_CreateDXGIFactory1 pCreate = (PFN_CreateDXGIFactory1)(void*)GetProcAddress(hDxgi, "CreateDXGIFactory1");
        if (pCreate) {
            /* IID_IDXGIFactory1 = {770aae78-f26f-4dba-a829-253c83d1b387} */
            static const GUID iid_fac1 = {0x770aae78, 0xf26f, 0x4dba, {0xa8, 0x29, 0x25, 0x3c, 0x83, 0xd1, 0xb3, 0x87}};
            IDXGIFactory1* fac = NULL;
            if (SUCCEEDED(pCreate(&iid_fac1, (void**)&fac)) && fac) {
                SIZE_T bestVram = 0;
                IDXGIAdapter1* ad = NULL;
                for (UINT i = 0; IDXGIFactory1_EnumAdapters1(fac, i, &ad) == S_OK; ++i) {
                    DXGI_ADAPTER_DESC1 desc;
                    if (SUCCEEDED(IDXGIAdapter1_GetDesc1(ad, &desc))) {
                        if ((desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) == 0 && desc.DedicatedVideoMemory >= bestVram) {
                            bestVram = desc.DedicatedVideoMemory;
                            telem->gpu_vendor = desc.VendorId;
                            telem->gpu_device = desc.DeviceId;
                            telem->vram_mb = (uint32_t)(desc.DedicatedVideoMemory / (1024ULL * 1024ULL));
                            WideCharToMultiByte(CP_UTF8, 0, desc.Description, -1,
                                                telem->gpu_name, (int)sizeof(telem->gpu_name), NULL, NULL);
                            telem->gpu_name[sizeof(telem->gpu_name) - 1] = '\0';
                        }
                    }
                    IDXGIAdapter1_Release(ad);
                    ad = NULL;
                }
                IDXGIFactory1_Release(fac);
            }
        }
        FreeLibrary(hDxgi);
    }

    if (g_cfg.max_generated_cap > 0) {
        telem->vram_cap_mult = (uint32_t)g_cfg.max_generated_cap;
    } else if (telem->vram_mb == 0) {
        telem->vram_cap_mult = 2; /* Safe 3X default if DXGI unreachable */
    } else if (telem->vram_mb <= 8704u) {
        telem->vram_cap_mult = 1; /* 2X max for <= 8GB VRAM (prevents Issue #60 OOM / #46 MMU freeze) */
    } else if (telem->vram_mb <= 12800u) {
        telem->vram_cap_mult = 2; /* 3X max for 10-12GB VRAM */
    } else {
        telem->vram_cap_mult = 4; /* 5X max for 16GB+ VRAM */
    }
}

static void InitTelemetryShm(void) {
    g_telem = &g_telem_fallback;
    g_shm_handle = CreateFileMappingW(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE, 0,
                                      (DWORD)sizeof(SI_ANR_Telemetry_v2), L"Local\\SI_ANR_Turbo_Telemetry_v2");
    if (g_shm_handle) {
        void* view = MapViewOfFile(g_shm_handle, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(SI_ANR_Telemetry_v2));
        if (view) g_telem = (SI_ANR_Telemetry_v2*)view;
    }
    memset(g_telem, 0, sizeof(*g_telem));
    g_telem->magic = 0x53494154u;
    g_telem->version = 2u;
    g_telem->pid = (uint32_t)GetCurrentProcessId();
    g_telem->hud_shield_active = (uint32_t)(g_cfg.hud_shield ? 1 : 0);
    g_telem->spike_guard_active = (uint32_t)(g_cfg.spike_guard_ms > 0.0f ? 1 : 0);
    g_telem->crash_shield_active = (uint32_t)(g_cfg.crash_shield ? 1 : 0);
}

static int EnsureCoreLoaded(void) {
    if (InterlockedCompareExchange(&g_init_done, 0, 0) == 1) {
        return g_core_mod != NULL;
    }
    AcquireSRWLockExclusive(&g_init_lock);
    if (g_init_done == 0) {
        if (!g_dll_dir[0] && g_self_inst) {
            wchar_t full[MAX_PATH] = {0};
            DWORD n = GetModuleFileNameW(g_self_inst, full, MAX_PATH);
            if (n > 0 && n < MAX_PATH) {
                wchar_t* slash = wcsrchr(full, L'\\');
                if (!slash) slash = wcsrchr(full, L'/');
                if (slash) *slash = L'\0';
                wcsncpy(g_dll_dir, full, MAX_PATH - 1);
            }
        }
        LoadTurboIni();
        if (!g_eval_cs_ready) {
            InitializeCriticalSection(&g_eval_cs);
            QueryPerformanceFrequency(&g_qpc_freq);
            g_eval_cs_ready = 1;
        }
        if (g_tls_idx == TLS_OUT_OF_INDEXES) {
            g_tls_idx = TlsAlloc();
        }
        if (g_cfg.crash_shield && !g_veh_handle) {
            g_veh_handle = AddVectoredExceptionHandler(1, TurboVehHandler);
        }

        InitTelemetryShm();
        DetectPrimaryGpuAndComputeCap(g_telem);

        if (g_cfg.enable_barrier_elide) {
            SetEnvironmentVariableA("NR_BARRIER_ELIDE", "1");
            g_telem->barrier_elide_active = 1;
        }

        wchar_t corePath[MAX_PATH];
        _snwprintf(corePath, MAX_PATH - 1, L"%ls\\nvngx_dlssg_core.dll", g_dll_dir);
        corePath[MAX_PATH - 1] = L'\0';
        g_core_mod = LoadLibraryW(corePath);
        if (g_core_mod) {
            g_core.NRFG_PresentationControl          = (PFN_NRFG_PresentationControl)(void*)GetProcAddress(g_core_mod, "NRFG_PresentationControl");
            g_core.D3D12_CreateFeature               = (PFN_CreateFeature)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_D3D12_CreateFeature");
            g_core.D3D12_EvaluateFeature             = (PFN_EvaluateFeature)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_D3D12_EvaluateFeature");
            g_core.D3D12_GetFeatureRequirements      = (PFN_D3D12_GetReqs)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_D3D12_GetFeatureRequirements");
            g_core.D3D12_GetScratchBufferSize        = (PFN_GetScratch)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_D3D12_GetScratchBufferSize");
            g_core.D3D12_Init                        = (PFN_D3D12_Init)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_D3D12_Init");
            g_core.D3D12_Init_Ext                    = (PFN_D3D12_Init_Ext)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_D3D12_Init_Ext");
            g_core.D3D12_PopulateParameters_Impl     = (PFN_Populate)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_D3D12_PopulateParameters_Impl");
            g_core.D3D12_ReleaseFeature              = (PFN_ReleaseFeature)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_D3D12_ReleaseFeature");
            g_core.D3D12_Shutdown                    = (PFN_Shutdown)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_D3D12_Shutdown");
            g_core.D3D12_Shutdown1                   = (PFN_Shutdown1)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_D3D12_Shutdown1");
            g_core.VK_CreateFeature                  = (PFN_CreateFeature)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_VULKAN_CreateFeature");
            g_core.VK_CreateFeature1                 = (PFN_VK_CreateFeature1)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_VULKAN_CreateFeature1");
            g_core.VK_EvaluateFeature                = (PFN_EvaluateFeature)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_VULKAN_EvaluateFeature");
            g_core.VK_GetFeatureRequirements         = (PFN_VK_GetReqs)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_VULKAN_GetFeatureRequirements");
            g_core.VK_GetScratchBufferSize           = (PFN_GetScratch)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_VULKAN_GetScratchBufferSize");
            g_core.VK_Init                           = (PFN_VK_Init)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_VULKAN_Init");
            g_core.VK_Init_Ext                       = (PFN_VK_Init_Ext)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_VULKAN_Init_Ext");
            g_core.VK_Init_Ext2                      = (PFN_VK_Init_Ext2)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_VULKAN_Init_Ext2");
            g_core.VK_PopulateParameters_Impl        = (PFN_Populate)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_VULKAN_PopulateParameters_Impl");
            g_core.VK_ReleaseFeature                 = (PFN_ReleaseFeature)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_VULKAN_ReleaseFeature");
            g_core.VK_Shutdown                       = (PFN_Shutdown)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_VULKAN_Shutdown");
            g_core.VK_Shutdown1                      = (PFN_Shutdown1)(void*)GetProcAddress(g_core_mod, "NVSDK_NGX_VULKAN_Shutdown1");
            g_telem->core_loaded = 1;
            TurboLog("Loaded nvngx_dlssg_core.dll | GPU='%s' (0x%04X:0x%04X) VRAM=%uMB | Cap=%uX | BarrierElide=%d",
                     g_telem->gpu_name, g_telem->gpu_vendor, g_telem->gpu_device, g_telem->vram_mb,
                     g_telem->vram_cap_mult + 1u, g_cfg.enable_barrier_elide);
        } else {
            TurboLog("ERROR: Failed to load nvngx_dlssg_core.dll (win32 err=%lu)", (unsigned long)GetLastError());
        }
        InterlockedExchange(&g_init_done, 1);
    }
    ReleaseSRWLockExclusive(&g_init_lock);
    return g_core_mod != NULL;
}

/* Core pre-evaluate intelligence executed on EVERY D3D12 & Vulkan EvaluateFeature frame */
static void FilterEvaluateParameters(const void* rawParams, uint32_t backendId) {
    g_telem->backend = backendId;
    g_telem->eval_count++;

    EnterCriticalSection(&g_eval_cs);

    LARGE_INTEGER now;
    QueryPerformanceCounter(&now);
    double dt_ms = 0.0;
    if (g_last_qpc.QuadPart != 0 && g_qpc_freq.QuadPart > 0) {
        dt_ms = (double)(now.QuadPart - g_last_qpc.QuadPart) * 1000.0 / (double)g_qpc_freq.QuadPart;
        if (dt_ms > 0.1 && dt_ms < 2000.0) {
            g_ema_ms = g_ema_ms * 0.90 + dt_ms * 0.10;
            g_telem->last_frame_ms = (float)dt_ms;
            g_telem->avg_frame_ms = (float)g_ema_ms;
            if (g_ema_ms > 0.1) g_telem->effective_fps = (float)(1000.0 / g_ema_ms);
        }
    }
    g_last_qpc = now;

    NGX_Param_Obj* p = SafeAsParam(rawParams);
    if (!p) {
        LeaveCriticalSection(&g_eval_cs);
        return;
    }
    NGX_Param_Vtbl* vt = p->vtbl;

    /* 1. VRAM-Aware MultiFrameCount Clamping (fixes Issue #60 OOM & #46 GPU MMU freeze) */
    unsigned int mfc = 1;
    if (vt->Get_UInt && vt->Get_UInt(p, "DLSSG.MultiFrameCount", &mfc) == NVSDK_NGX_RESULT_SUCCESS) {
        if (mfc > g_telem->vram_cap_mult && vt->Set_UInt) {
            vt->Set_UInt(p, "DLSSG.MultiFrameCount", g_telem->vram_cap_mult);
            mfc = g_telem->vram_cap_mult;
            g_telem->vram_clamped_frames++;
        }
    }

    /* 2. Missing HUDLess / UI Buffer Shield (fixes Issue #24 HUD/Minimap jitter) */
    if (g_cfg.hud_shield && vt->Get_VoidPtr) {
        void* hudless = NULL;
        void* ui = NULL;
        void* uialpha = NULL;
        vt->Get_VoidPtr(p, "DLSSG.HUDLess", &hudless);
        vt->Get_VoidPtr(p, "DLSSG.UI", &ui);
        vt->Get_VoidPtr(p, "DLSSG.UIAlpha", &uialpha);
        if (!hudless && !ui && !uialpha) {
            g_telem->hudless_missing_frames++;
            if (vt->Set_UInt) {
                vt->Set_UInt(p, "DLSSG.UserInterfaceRecompositionEnabled", 1u);
                if (mfc > 1u) {
                    vt->Set_UInt(p, "DLSSG.MultiFrameCount", 1u);
                }
                if (g_cfg.strict_hud_fallback) {
                    vt->Set_UInt(p, "DLSSG.OutputDisableInterpolation", 1u);
                }
            }
        }
    }

    /* 3. Camera Teleport & FOV Jump Scene-Cut Auto-Reset (fixes Issue #68 optical flow ghost tearing) */
    if (g_cfg.scene_cut_auto_reset && vt->Get_Float) {
        float cx = 0.0f, cy = 0.0f, cz = 0.0f, fov = 0.0f;
        uint32_t r1 = vt->Get_Float(p, "DLSSG.CameraPosX", &cx);
        uint32_t r2 = vt->Get_Float(p, "DLSSG.CameraPosY", &cy);
        uint32_t r3 = vt->Get_Float(p, "DLSSG.CameraPosZ", &cz);
        uint32_t r4 = vt->Get_Float(p, "DLSSG.CameraFOV", &fov);
        if (r1 == NVSDK_NGX_RESULT_SUCCESS && r2 == NVSDK_NGX_RESULT_SUCCESS && r3 == NVSDK_NGX_RESULT_SUCCESS) {
            if (g_have_cam) {
                float dx = cx - g_prev_cam[0];
                float dy = cy - g_prev_cam[1];
                float dz = cz - g_prev_cam[2];
                float dist2 = dx * dx + dy * dy + dz * dz;
                float dfov = (r4 == NVSDK_NGX_RESULT_SUCCESS) ? fabsf(fov - g_prev_fov) : 0.0f;
                if (dist2 > 625.0f || dfov > 0.35f) {
                    unsigned int alreadyReset = 0;
                    if (vt->Get_UInt) vt->Get_UInt(p, "DLSSG.Reset", &alreadyReset);
                    if (!alreadyReset && vt->Set_UInt) {
                        vt->Set_UInt(p, "DLSSG.Reset", 1u);
                        vt->Set_UInt(p, "DLSSG.AutomodeOverrideReset", 1u);
                        g_telem->scene_cuts_injected++;
                    }
                }
            }
            g_prev_cam[0] = cx; g_prev_cam[1] = cy; g_prev_cam[2] = cz;
            if (r4 == NVSDK_NGX_RESULT_SUCCESS) g_prev_fov = fov;
            g_have_cam = 1;
        }
    }

    /* 4. Frame-Time Spike & Menu Hitch Suppressor (fixes Issue #64 choppy FG) */
    if (g_cfg.spike_guard_ms > 0.0f && dt_ms > 0.0) {
        double dyn_thresh = fmax((double)g_cfg.spike_guard_ms, g_ema_ms * 2.4);
        unsigned int notRendering = 0;
        if (vt->Get_UInt) vt->Get_UInt(p, "DLSSG.NotRenderingGameFrames", &notRendering);
        if (notRendering || (g_telem->eval_count > 10 && dt_ms > dyn_thresh)) {
            g_spike_cooldown = notRendering ? 1 : 2;
        }
        if (g_spike_cooldown > 0) {
            if (vt->Set_UInt) vt->Set_UInt(p, "DLSSG.OutputDisableInterpolation", 1u);
            g_telem->spike_suppressed_frames++;
            g_spike_cooldown--;
        }
    }

    LeaveCriticalSection(&g_eval_cs);
}

/* =========================================================================
 * Exported DLL Interface (Exact 23 Exports Matching Official nvngx_dlssg.dll)
 * ========================================================================= */

int __cdecl NRFG_PresentationControl(void* out_desc, void* in_ctrl) {
    if (!EnsureCoreLoaded() || !g_core.NRFG_PresentationControl) return 0;
    return g_core.NRFG_PresentationControl(out_desc, in_ctrl);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_Init(unsigned long long appId, const wchar_t* dataPath, void* device, uint32_t sdkVer) {
    if (!EnsureCoreLoaded() || !g_core.D3D12_Init) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!device) return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    return g_core.D3D12_Init(appId, dataPath, device, sdkVer);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_Init_Ext(unsigned long long appId, const wchar_t* dataPath, void* device, uint32_t sdkVer, const void* params) {
    if (!EnsureCoreLoaded() || !g_core.D3D12_Init_Ext) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!device) return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    return g_core.D3D12_Init_Ext(appId, dataPath, device, sdkVer, params);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_Shutdown(void) {
    if (!EnsureCoreLoaded() || !g_core.D3D12_Shutdown) return NVSDK_NGX_RESULT_SUCCESS;
    return g_core.D3D12_Shutdown();
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_Shutdown1(void* device) {
    if (!EnsureCoreLoaded() || !g_core.D3D12_Shutdown1) return NVSDK_NGX_RESULT_SUCCESS;
    return g_core.D3D12_Shutdown1(device);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_GetScratchBufferSize(uint32_t featId, const void* params, size_t* outBytes) {
    if (!EnsureCoreLoaded() || !g_core.D3D12_GetScratchBufferSize) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!outBytes) return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    return g_core.D3D12_GetScratchBufferSize(featId, params, outBytes);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_GetFeatureRequirements(void* adapter, const void* info, void* outSup) {
    if (!EnsureCoreLoaded() || !g_core.D3D12_GetFeatureRequirements) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!info || !outSup) return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    return g_core.D3D12_GetFeatureRequirements(adapter, info, outSup);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_PopulateParameters_Impl(void* params) {
    if (!EnsureCoreLoaded() || !g_core.D3D12_PopulateParameters_Impl) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!params) return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    return g_core.D3D12_PopulateParameters_Impl(params);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_CreateFeature(void* cmdList, uint32_t featId, void* params, void** outHandle) {
    if (!EnsureCoreLoaded() || !g_core.D3D12_CreateFeature) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!cmdList || !params || !outHandle) {
        if (g_telem) g_telem->crashes_blocked++;
        TurboLog("Blocked unsafe D3D12_CreateFeature null arg (cmd=%p params=%p out=%p)", cmdList, params, (void*)outHandle);
        return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    }
    ShieldTls* st = g_cfg.crash_shield ? GetShieldTls() : NULL;
    if (st) {
        if (setjmp(st->env) != 0) {
            g_telem->crashes_blocked++;
            TurboLog("CRASH SHIELD caught 0x%08lX inside D3D12_CreateFeature at %p",
                     (unsigned long)st->exception_code, st->exception_addr);
            return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
        }
        st->active = 1;
    }
    NVSDK_NGX_Result res = g_core.D3D12_CreateFeature(cmdList, featId, params, outHandle);
    if (st) st->active = 0;
    return res;
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_ReleaseFeature(void* handle) {
    if (!handle) return NVSDK_NGX_RESULT_SUCCESS;
    if (!EnsureCoreLoaded() || !g_core.D3D12_ReleaseFeature) return NVSDK_NGX_RESULT_SUCCESS;
    return g_core.D3D12_ReleaseFeature(handle);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_EvaluateFeature(void* cmdList, const void* featHandle, const void* params, void* callback) {
    if (!EnsureCoreLoaded() || !g_core.D3D12_EvaluateFeature) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (InterlockedCompareExchange(&g_fg_bypass, 0, 0) == 1) return NVSDK_NGX_RESULT_SUCCESS;
    if (!cmdList || !featHandle || !params) {
        if (g_telem) g_telem->crashes_blocked++;
        return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    }
    FilterEvaluateParameters(params, 1u);

    ShieldTls* st = g_cfg.crash_shield ? GetShieldTls() : NULL;
    if (st) {
        if (setjmp(st->env) != 0) {
            InterlockedExchange(&g_fg_bypass, 1);
            g_telem->fg_bypass_engaged = 1;
            g_telem->crashes_blocked++;
            TurboLog("CRASH SHIELD caught 0x%08lX inside D3D12_EvaluateFeature at %p -> engaged safe FG passthrough",
                     (unsigned long)st->exception_code, st->exception_addr);
            return NVSDK_NGX_RESULT_SUCCESS;
        }
        st->active = 1;
    }
    NVSDK_NGX_Result res = g_core.D3D12_EvaluateFeature(cmdList, featHandle, params, callback);
    if (st) st->active = 0;
    return res;
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_Init(unsigned long long appId, const wchar_t* dataPath, void* inst, void* pd, void* dev, void* gipa, void* gdpa, const void* featInfo, uint32_t sdkVer) {
    if (!EnsureCoreLoaded() || !g_core.VK_Init) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!dev) return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    return g_core.VK_Init(appId, dataPath, inst, pd, dev, gipa, gdpa, featInfo, sdkVer);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_Init_Ext(unsigned long long appId, const wchar_t* dataPath, void* inst, void* pd, void* dev, uint32_t sdkVer, const void* params) {
    if (!EnsureCoreLoaded() || !g_core.VK_Init_Ext) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!dev) return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    return g_core.VK_Init_Ext(appId, dataPath, inst, pd, dev, sdkVer, params);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_Init_Ext2(unsigned long long appId, const wchar_t* dataPath, void* inst, void* pd, void* dev, void* gipa, void* gdpa, uint32_t sdkVer, const void* params) {
    if (!EnsureCoreLoaded() || !g_core.VK_Init_Ext2) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!dev) return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    return g_core.VK_Init_Ext2(appId, dataPath, inst, pd, dev, gipa, gdpa, sdkVer, params);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_Shutdown(void) {
    if (!EnsureCoreLoaded() || !g_core.VK_Shutdown) return NVSDK_NGX_RESULT_SUCCESS;
    return g_core.VK_Shutdown();
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_Shutdown1(void* dev) {
    if (!EnsureCoreLoaded() || !g_core.VK_Shutdown1) return NVSDK_NGX_RESULT_SUCCESS;
    return g_core.VK_Shutdown1(dev);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_GetScratchBufferSize(uint32_t featId, const void* params, size_t* outBytes) {
    if (!EnsureCoreLoaded() || !g_core.VK_GetScratchBufferSize) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!outBytes) return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    return g_core.VK_GetScratchBufferSize(featId, params, outBytes);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_GetFeatureRequirements(const void* inst, const void* pd, const void* info, void* outSup) {
    if (!EnsureCoreLoaded() || !g_core.VK_GetFeatureRequirements) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!info || !outSup) return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    return g_core.VK_GetFeatureRequirements(inst, pd, info, outSup);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_PopulateParameters_Impl(void* params) {
    if (!EnsureCoreLoaded() || !g_core.VK_PopulateParameters_Impl) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!params) return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    return g_core.VK_PopulateParameters_Impl(params);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_CreateFeature(void* cmdBuf, uint32_t featId, void* params, void** outHandle) {
    if (!EnsureCoreLoaded() || !g_core.VK_CreateFeature) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!cmdBuf || !params || !outHandle) {
        if (g_telem) g_telem->crashes_blocked++;
        return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    }
    ShieldTls* st = g_cfg.crash_shield ? GetShieldTls() : NULL;
    if (st) {
        if (setjmp(st->env) != 0) {
            g_telem->crashes_blocked++;
            TurboLog("CRASH SHIELD caught 0x%08lX inside VULKAN_CreateFeature at %p",
                     (unsigned long)st->exception_code, st->exception_addr);
            return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
        }
        st->active = 1;
    }
    NVSDK_NGX_Result res = g_core.VK_CreateFeature(cmdBuf, featId, params, outHandle);
    if (st) st->active = 0;
    return res;
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_CreateFeature1(void* dev, void* cmdList, uint32_t featId, void* params, void** outHandle) {
    if (!EnsureCoreLoaded() || !g_core.VK_CreateFeature1) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (!dev || !cmdList || !params || !outHandle) {
        if (g_telem) g_telem->crashes_blocked++;
        return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    }
    ShieldTls* st = g_cfg.crash_shield ? GetShieldTls() : NULL;
    if (st) {
        if (setjmp(st->env) != 0) {
            g_telem->crashes_blocked++;
            TurboLog("CRASH SHIELD caught 0x%08lX inside VULKAN_CreateFeature1 at %p",
                     (unsigned long)st->exception_code, st->exception_addr);
            return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
        }
        st->active = 1;
    }
    NVSDK_NGX_Result res = g_core.VK_CreateFeature1(dev, cmdList, featId, params, outHandle);
    if (st) st->active = 0;
    return res;
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_ReleaseFeature(void* handle) {
    if (!handle) return NVSDK_NGX_RESULT_SUCCESS;
    if (!EnsureCoreLoaded() || !g_core.VK_ReleaseFeature) return NVSDK_NGX_RESULT_SUCCESS;
    return g_core.VK_ReleaseFeature(handle);
}

NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_EvaluateFeature(void* cmdList, const void* featHandle, const void* params, void* callback) {
    if (!EnsureCoreLoaded() || !g_core.VK_EvaluateFeature) return NVSDK_NGX_RESULT_FAIL_NOT_INIT;
    if (InterlockedCompareExchange(&g_fg_bypass, 0, 0) == 1) return NVSDK_NGX_RESULT_SUCCESS;
    if (!cmdList || !featHandle || !params) {
        if (g_telem) g_telem->crashes_blocked++;
        return NVSDK_NGX_RESULT_FAIL_INVALID_PARAM;
    }
    FilterEvaluateParameters(params, 2u);

    ShieldTls* st = g_cfg.crash_shield ? GetShieldTls() : NULL;
    if (st) {
        if (setjmp(st->env) != 0) {
            InterlockedExchange(&g_fg_bypass, 1);
            g_telem->fg_bypass_engaged = 1;
            g_telem->crashes_blocked++;
            TurboLog("CRASH SHIELD caught 0x%08lX inside VULKAN_EvaluateFeature at %p -> engaged safe FG passthrough",
                     (unsigned long)st->exception_code, st->exception_addr);
            return NVSDK_NGX_RESULT_SUCCESS;
        }
        st->active = 1;
    }
    NVSDK_NGX_Result res = g_core.VK_EvaluateFeature(cmdList, featHandle, params, callback);
    if (st) st->active = 0;
    return res;
}

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved) {
    (void)lpvReserved;
    if (fdwReason == DLL_PROCESS_ATTACH) {
        g_self_inst = hinstDLL;
        DisableThreadLibraryCalls(hinstDLL);
    } else if (fdwReason == DLL_THREAD_DETACH) {
        if (g_tls_idx != TLS_OUT_OF_INDEXES) {
            ShieldTls* st = (ShieldTls*)TlsGetValue(g_tls_idx);
            if (st) {
                HeapFree(GetProcessHeap(), 0, st);
                TlsSetValue(g_tls_idx, NULL);
            }
        }
    } else if (fdwReason == DLL_PROCESS_DETACH) {
        if (g_veh_handle) {
            RemoveVectoredExceptionHandler(g_veh_handle);
            g_veh_handle = NULL;
        }
        if (g_telem && g_telem != &g_telem_fallback) {
            UnmapViewOfFile(g_telem);
            g_telem = NULL;
        }
        if (g_shm_handle) {
            CloseHandle(g_shm_handle);
            g_shm_handle = NULL;
        }
        if (g_core_mod && !lpvReserved) {
            FreeLibrary(g_core_mod);
            g_core_mod = NULL;
        }
        if (g_eval_cs_ready) {
            DeleteCriticalSection(&g_eval_cs);
            g_eval_cs_ready = 0;
        }
        if (g_tls_idx != TLS_OUT_OF_INDEXES) {
            TlsFree(g_tls_idx);
            g_tls_idx = TLS_OUT_OF_INDEXES;
        }
    }
    return TRUE;
}
