/* Resolution preferences store dimensions, not unstable firmware mode indexes. */
#define DISPLAY_MODE_LIMIT 256U
#define DISPLAY_PAGE_SIZE 8U
#define DISPLAY_CONFIRM_SECONDS 15U
static EFI_GRAPHICS_OUTPUT_PROTOCOL *gSettingsDisplayGop;
static UINT32 gSettingsDisplayDefaultMode;
static UINT8 gSettingsDisplayInitialized;
typedef struct { UINT32 mode, width, height; } SETTINGS_DISPLAY_MODE;
#ifndef TINYGPT_NATIVE
#include "display_console.inc"
#endif

static int settings_display_init(void) {
    static EFI_GUID guid = {0x9042a9de,0x23dc,0x4a38,{0x96,0xfb,0x7a,0xde,0xd0,0x80,0x51,0x6a}};
    if (!gSettingsDisplayInitialized) {
        gSettingsDisplayInitialized = 1;
        /* Prefer the active console's GPU; LocateProtocol is the single-GPU fallback. */
        if (gST->BootServices->HandleProtocol(gST->ConsoleOutHandle, &guid, (void **)&gSettingsDisplayGop) != EFI_SUCCESS)
            gSettingsDisplayGop = (void *)0;
        if (!gSettingsDisplayGop && gST->BootServices->LocateProtocol(&guid, (void *)0, (void **)&gSettingsDisplayGop) != EFI_SUCCESS)
            gSettingsDisplayGop = (void *)0;
        if (gSettingsDisplayGop && gSettingsDisplayGop->Mode)
            gSettingsDisplayDefaultMode = gSettingsDisplayGop->Mode->Mode;
    }
    return gSettingsDisplayGop && gSettingsDisplayGop->Mode && gSettingsDisplayGop->Mode->Info &&
        gSettingsDisplayGop->QueryMode && gSettingsDisplayGop->SetMode && gSettingsDisplayGop->Blt;
}

static int settings_display_query(UINT32 mode, SETTINGS_DISPLAY_MODE *result) {
    EFI_GRAPHICS_OUTPUT_MODE_INFORMATION *info = (void *)0;
    UINTN bytes = 0;
    EFI_STATUS status = gSettingsDisplayGop->QueryMode(gSettingsDisplayGop, mode, &bytes, &info);
    int valid = status == EFI_SUCCESS && info && bytes >= sizeof(*info) &&
        info->HorizontalResolution >= 640U && info->HorizontalResolution <= 1920U &&
        info->VerticalResolution >= 480U && info->VerticalResolution <= 1080U;
    if (valid) *result = (SETTINGS_DISPLAY_MODE){mode, info->HorizontalResolution, info->VerticalResolution};
    if (info) gST->BootServices->FreePool(info);
    return valid;
}

static int settings_display_set(UINT32 mode) {
    if (gSettingsDisplayGop->SetMode(gSettingsDisplayGop, mode) != EFI_SUCCESS ||
        gSettingsDisplayGop->Mode->Mode != mode) return 0;
#ifndef TINYGPT_NATIVE
    display_console_install();
#endif
    settings_use_default_color();
    if (gST->ConOut->ClearScreen(gST->ConOut) != EFI_SUCCESS) return 0;
    console_update_geometry();
    /* Old history was wrapped at a different width; never repaint stale rows. */
    scrollback_reset();
    return 1;
}

static int settings_display_load(void) {
    int available = settings_display_init();
    if (!gSettings.displayWidth || !gSettings.displayHeight) return 1;
    if (!available) return 0;
    for (UINT32 mode = 0; mode < gSettingsDisplayGop->Mode->MaxMode && mode < DISPLAY_MODE_LIMIT; mode++) {
        SETTINGS_DISPLAY_MODE info;
        if (!settings_display_query(mode, &info) || info.width != gSettings.displayWidth || info.height != gSettings.displayHeight) continue;
        if (settings_display_set(mode)) return 1;
        (void)settings_display_set(gSettingsDisplayDefaultMode);
        return 0;
    }
    return 0;
}

static void settings_display_print_current(void) {
    if (!settings_display_init()) { print("unavailable (text-only console)"); return; }
    print_u64(gSettingsDisplayGop->Mode->Info->HorizontalResolution);
    print(" x ");
    print_u64(gSettingsDisplayGop->Mode->Info->VerticalResolution);
    if (!gSettings.displayWidth) print(" (boot default)");
}

static int settings_display_confirm(void) {
    EFI_INPUT_KEY key;
    UINT64 start = timer_count();
    print("Keep this resolution? Press Y to keep, N / Esc to undo.\n");
    print("Reverting automatically in 15 seconds unless confirmed.\n");
    while (timer_count() - start < gTimerHz * DISPLAY_CONFIRM_SECONDS) {
        if (!poll_input_key(&key)) { __asm__ volatile("yield"); continue; }
        int keep = key.UnicodeChar == 'y' || key.UnicodeChar == 'Y';
        if (keep || key.ScanCode == 23 || key.UnicodeChar == 'n' || key.UnicodeChar == 'N') {
            /* Do not leave the Enter from a serial 'y\n' at the next menu. */
            for (UINTN i = 0; i < 64U && poll_input_key(&key); i++) {}
            return keep;
        }
    }
    return 0;
}

static const char *settings_choose_display(void) {
    SETTINGS_DISPLAY_MODE modes[DISPLAY_MODE_LIMIT];
    UINTN count = 0, page = 0;
    char answer[32];
    if (!settings_display_init()) return "Resolution changes unavailable: no graphics output device.";
    for (UINT32 mode = 0; mode < gSettingsDisplayGop->Mode->MaxMode && mode < DISPLAY_MODE_LIMIT; mode++) {
        SETTINGS_DISPLAY_MODE info;
        if (!settings_display_query(mode, &info)) continue;
        UINTN i;
        for (i = 0; i < count; i++) if (modes[i].width == info.width && modes[i].height == info.height) break;
        if (i == count) modes[count++] = info;
    }
    if (!count) return "No supported screen resolutions (640x480 through 1920x1080).";
    for (;;) {
        gST->ConOut->ClearScreen(gST->ConOut);
        print("=== Screen resolution ===\n\nCurrent: "); settings_display_print_current();
        print("\nChoose a mode to preview. Unconfirmed changes revert in 15 seconds.\n\n");
        for (UINTN i = page; i < count && i < page + DISPLAY_PAGE_SIZE; i++) {
            print("  "); print_u64(i + 1U); print("  "); print_u64(modes[i].width);
            print(" x "); print_u64(modes[i].height); print("\n");
        }
        print("\nD: boot default   N/P: next/previous page   0: cancel\nResolution: ");
        read_line(answer, sizeof(answer));
        if (streq(answer, "0")) return "Resolution change canceled.";
        if (streq(answer, "n") || streq(answer, "N")) { if (page + DISPLAY_PAGE_SIZE < count) page += DISPLAY_PAGE_SIZE; continue; }
        if (streq(answer, "p") || streq(answer, "P")) { if (page >= DISPLAY_PAGE_SIZE) page -= DISPLAY_PAGE_SIZE; continue; }
        UINT32 choice;
        SETTINGS_DISPLAY_MODE selected;
        int useDefault = streq(answer, "d") || streq(answer, "D");
        if (useDefault) {
            if (!settings_display_query(gSettingsDisplayDefaultMode, &selected)) return "Boot default mode is unavailable.";
        } else {
            if (!settings_parse_uint32(answer, &choice) || !choice || choice > count) return "Invalid resolution selection; nothing changed.";
            selected = modes[choice - 1U];
        }
        UINT32 previous = gSettingsDisplayGop->Mode->Mode;
        int applied = settings_display_set(selected.mode);
        if (!applied || !settings_display_confirm()) {
            if (!settings_display_set(previous)) return "Display restore failed; reboot to restore the saved mode. Nothing saved.";
            return applied ? "Resolution reverted; nothing saved." : "Display mode failed; previous resolution restored.";
        }
        gSettings.displayWidth = useDefault ? 0U : selected.width;
        gSettings.displayHeight = useDefault ? 0U : selected.height;
        return settings_save_notice();
    }
}
