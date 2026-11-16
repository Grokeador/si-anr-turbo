/*
 * Mock nvngx_dlssg_core.dll + NGX Parameter test harness for automated unit/integration tests
 * of SI-ANR-Turbo's compiled x64 nvngx_dlssg.dll Smart-Shield proxy.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define NVSDK_NGX_Result uint32_t
#define NVSDK_NGX_RESULT_SUCCESS 0x00000001u

typedef struct MockEntry {
    char key[64];
    int kind; /* 1=uint, 2=float, 3=ptr */
    unsigned int uval;
    float fval;
    void* pval;
} MockEntry;

typedef struct NGX_Param_Vtbl {
    void     (WINAPI *Set_VoidPtr)(void* self, const char* name, void* val);
    void     (WINAPI *Set_D3D12)(void* self, const char* name, void* val);
    void     (WINAPI *Set_D3D11)(void* self, const char* name, void* val);
    void     (WINAPI *Set_Int)(void* self, const char* name, int val);
    void     (WINAPI *Set_UInt)(void* self, const char* name, unsigned int val);
    void     (WINAPI *Set_Double)(void* self, const char* name, double val);
    void     (WINAPI *Set_Float)(void* self, const char* name, float val);
    void     (WINAPI *Set_ULL)(void* self, const char* name, unsigned long long val);
    uint32_t (WINAPI *Get_VoidPtr)(void* self, const char* name, void** out);
    uint32_t (WINAPI *Get_D3D12)(void* self, const char* name, void** out);
    uint32_t (WINAPI *Get_D3D11)(void* self, const char* name, void** out);
    uint32_t (WINAPI *Get_Int)(void* self, const char* name, int* out);
    uint32_t (WINAPI *Get_UInt)(void* self, const char* name, unsigned int* out);
    uint32_t (WINAPI *Get_Double)(void* self, const char* name, double* out);
    uint32_t (WINAPI *Get_Float)(void* self, const char* name, float* out);
    uint32_t (WINAPI *Get_ULL)(void* self, const char* name, unsigned long long* out);
    void     (WINAPI *Reset)(void* self);
} NGX_Param_Vtbl;

typedef struct MockParam {
    NGX_Param_Vtbl* vtbl;
    MockEntry entries[32];
    int count;
} MockParam;

static MockEntry* find_or_add(MockParam* m, const char* name, int create) {
    for (int i = 0; i < m->count; ++i) {
        if (strcmp(m->entries[i].key, name) == 0) return &m->entries[i];
    }
    if (!create || m->count >= 32) return NULL;
    MockEntry* e = &m->entries[m->count++];
    memset(e, 0, sizeof(*e));
    strncpy(e->key, name, sizeof(e->key) - 1);
    return e;
}

static void WINAPI m_Set_VoidPtr(void* s, const char* n, void* v) { MockEntry* e = find_or_add((MockParam*)s, n, 1); if (e) { e->kind = 3; e->pval = v; } }
static void WINAPI m_Set_D3D12(void* s, const char* n, void* v) { m_Set_VoidPtr(s, n, v); }
static void WINAPI m_Set_D3D11(void* s, const char* n, void* v) { m_Set_VoidPtr(s, n, v); }
static void WINAPI m_Set_Int(void* s, const char* n, int v) { MockEntry* e = find_or_add((MockParam*)s, n, 1); if (e) { e->kind = 1; e->uval = (unsigned int)v; } }
static void WINAPI m_Set_UInt(void* s, const char* n, unsigned int v) { MockEntry* e = find_or_add((MockParam*)s, n, 1); if (e) { e->kind = 1; e->uval = v; } }
static void WINAPI m_Set_Double(void* s, const char* n, double v) { MockEntry* e = find_or_add((MockParam*)s, n, 1); if (e) { e->kind = 2; e->fval = (float)v; } }
static void WINAPI m_Set_Float(void* s, const char* n, float v) { MockEntry* e = find_or_add((MockParam*)s, n, 1); if (e) { e->kind = 2; e->fval = v; } }
static void WINAPI m_Set_ULL(void* s, const char* n, unsigned long long v) { m_Set_UInt(s, n, (unsigned int)v); }
static uint32_t WINAPI m_Get_VoidPtr(void* s, const char* n, void** out) { MockEntry* e = find_or_add((MockParam*)s, n, 0); if (!e || !out) return 0xBAD00001u; *out = e->pval; return 1u; }
static uint32_t WINAPI m_Get_D3D12(void* s, const char* n, void** out) { return m_Get_VoidPtr(s, n, out); }
static uint32_t WINAPI m_Get_D3D11(void* s, const char* n, void** out) { return m_Get_VoidPtr(s, n, out); }
static uint32_t WINAPI m_Get_Int(void* s, const char* n, int* out) { MockEntry* e = find_or_add((MockParam*)s, n, 0); if (!e || !out) return 0xBAD00001u; *out = (int)e->uval; return 1u; }
static uint32_t WINAPI m_Get_UInt(void* s, const char* n, unsigned int* out) { MockEntry* e = find_or_add((MockParam*)s, n, 0); if (!e || !out) return 0xBAD00001u; *out = e->uval; return 1u; }
static uint32_t WINAPI m_Get_Double(void* s, const char* n, double* out) { MockEntry* e = find_or_add((MockParam*)s, n, 0); if (!e || !out) return 0xBAD00001u; *out = (double)e->fval; return 1u; }
static uint32_t WINAPI m_Get_Float(void* s, const char* n, float* out) { MockEntry* e = find_or_add((MockParam*)s, n, 0); if (!e || !out) return 0xBAD00001u; *out = e->fval; return 1u; }
static uint32_t WINAPI m_Get_ULL(void* s, const char* n, unsigned long long* out) { MockEntry* e = find_or_add((MockParam*)s, n, 0); if (!e || !out) return 0xBAD00001u; *out = (unsigned long long)e->uval; return 1u; }
static void WINAPI m_Reset(void* s) { ((MockParam*)s)->count = 0; }

static NGX_Param_Vtbl g_vtbl = {
    m_Set_VoidPtr, m_Set_D3D12, m_Set_D3D11, m_Set_Int, m_Set_UInt,
    m_Set_Double, m_Set_Float, m_Set_ULL,
    m_Get_VoidPtr, m_Get_D3D12, m_Get_D3D11, m_Get_Int, m_Get_UInt,
    m_Get_Double, m_Get_Float, m_Get_ULL, m_Reset
};

/* Helpers exported solely for test harness control */
__declspec(dllexport) void* __cdecl MockCreateParams(void) {
    MockParam* m = (MockParam*)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(MockParam));
    m->vtbl = &g_vtbl;
    return m;
}
__declspec(dllexport) void __cdecl MockDestroyParams(void* p) { if (p) HeapFree(GetProcessHeap(), 0, p); }
__declspec(dllexport) void __cdecl MockSetUInt(void* p, const char* n, unsigned int v) { m_Set_UInt(p, n, v); }
__declspec(dllexport) unsigned int __cdecl MockGetUInt(void* p, const char* n) { unsigned int v = 9999u; m_Get_UInt(p, n, &v); return v; }
__declspec(dllexport) void __cdecl MockSetFloat(void* p, const char* n, float v) { m_Set_Float(p, n, v); }
__declspec(dllexport) void __cdecl MockSetPtr(void* p, const char* n, void* v) { m_Set_VoidPtr(p, n, v); }
__declspec(dllexport) int __cdecl MockWasBarrierElideSeen(void) {
    char buf[8] = {0};
    return (GetEnvironmentVariableA("NR_BARRIER_ELIDE", buf, sizeof(buf)) > 0 && buf[0] == '1') ? 1 : 0;
}

/* Mocked official ANR exports */
static int g_dummy_handle = 0x1234;
__declspec(dllexport) int __cdecl NRFG_PresentationControl(void* a, void* b) { (void)a; (void)b; return 77; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_Init(unsigned long long a, const wchar_t* b, void* c, uint32_t d) { (void)a;(void)b;(void)c;(void)d; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_Init_Ext(unsigned long long a, const wchar_t* b, void* c, uint32_t d, const void* e) { (void)a;(void)b;(void)c;(void)d;(void)e; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_Shutdown(void) { return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_Shutdown1(void* a) { (void)a; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_GetScratchBufferSize(uint32_t a, const void* b, size_t* c) { (void)a;(void)b; *c = 4096; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_GetFeatureRequirements(void* a, const void* b, void* c) { (void)a;(void)b;(void)c; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_PopulateParameters_Impl(void* a) { (void)a; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_CreateFeature(void* a, uint32_t b, void* c, void** out) { (void)a;(void)b;(void)c; *out = &g_dummy_handle; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_ReleaseFeature(void* a) { (void)a; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_D3D12_EvaluateFeature(void* a, const void* b, const void* params, void* cb) {
    (void)a; (void)b; (void)cb;
    unsigned int fault = 0;
    if (params && m_Get_UInt((void*)params, "TEST.TriggerFault", &fault) == 1u && fault == 1u) {
        volatile int* bad = (volatile int*)0;
        *bad = 42;
    }
    return 1u;
}
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_Init(unsigned long long a, const wchar_t* b, void* c, void* d, void* e, void* f, void* g, const void* h, uint32_t i) { (void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;(void)h;(void)i; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_Init_Ext(unsigned long long a, const wchar_t* b, void* c, void* d, void* e, uint32_t f, const void* g) { (void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_Init_Ext2(unsigned long long a, const wchar_t* b, void* c, void* d, void* e, void* f, void* g, uint32_t h, const void* i) { (void)a;(void)b;(void)c;(void)d;(void)e;(void)f;(void)g;(void)h;(void)i; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_Shutdown(void) { return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_Shutdown1(void* a) { (void)a; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_GetScratchBufferSize(uint32_t a, const void* b, size_t* c) { (void)a;(void)b; *c = 8192; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_GetFeatureRequirements(const void* a, const void* b, const void* c, void* d) { (void)a;(void)b;(void)c;(void)d; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_PopulateParameters_Impl(void* a) { (void)a; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_CreateFeature(void* a, uint32_t b, void* c, void** out) { (void)a;(void)b;(void)c; *out = &g_dummy_handle; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_CreateFeature1(void* a, void* b, uint32_t c, void* d, void** out) { (void)a;(void)b;(void)c;(void)d; *out = &g_dummy_handle; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_ReleaseFeature(void* a) { (void)a; return 1u; }
__declspec(dllexport) NVSDK_NGX_Result WINAPI NVSDK_NGX_VULKAN_EvaluateFeature(void* a, const void* b, const void* c, void* d) { (void)a;(void)b;(void)c;(void)d; return 1u; }
