/* UEFI GraphicsConsole caches its startup pixel dimensions. After a GOP mode
 * switch use our own bounded text renderer, not that stale firmware geometry.
 * GOP Blt handles RGB/BGR/bitmask/video-only devices without pixel assumptions. */
#include "../third_party/console-font/font8x19.h"
static EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL gDisplayConsole;
static EFI_SIMPLE_TEXT_OUTPUT_MODE gDisplayConsoleMode = {1, 0, 7, 0, 0, 1};
static EFI_SYSTEM_TABLE gDisplaySystemTable;
static const UINT32 gDisplayPalette[16] = {
    0x000000,0x0000aa,0x00aa00,0x00aaaa,0xaa0000,0xaa00aa,0xaa5500,0xaaaaaa,
    0x555555,0x5555ff,0x55ff55,0x55ffff,0xff5555,0xff55ff,0xffff55,0xffffff
};
static EFI_GRAPHICS_OUTPUT_BLT_PIXEL display_pixel(UINTN color) {
    UINT32 rgb = gDisplayPalette[color & 15U];
    return (EFI_GRAPHICS_OUTPUT_BLT_PIXEL){(UINT8)rgb, (UINT8)(rgb >> 8), (UINT8)(rgb >> 16), 0};
}
static EFI_STATUS display_console_query(EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *self, UINTN mode, UINTN *columns, UINTN *rows) {
    (void)self;
    if (mode) return EFI_UNSUPPORTED;
    *columns = gSettingsDisplayGop->Mode->Info->HorizontalResolution / NATIVE_FONT_WIDTH;
    *rows = gSettingsDisplayGop->Mode->Info->VerticalResolution / NATIVE_FONT_HEIGHT;
    return EFI_SUCCESS;
}
static EFI_STATUS display_console_attribute(EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *self, UINTN attribute) {
    (void)self;
    if (attribute > 0x7fU) return EFI_UNSUPPORTED;
    gDisplayConsoleMode.Attribute = (INT32)attribute;
    return EFI_SUCCESS;
}
static EFI_STATUS display_console_cursor(EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *self, UINTN x, UINTN y) {
    UINTN columns, rows;
    display_console_query(self, 0, &columns, &rows);
    if (x >= columns || y >= rows) return EFI_UNSUPPORTED;
    gDisplayConsoleMode.CursorColumn = (INT32)x;
    gDisplayConsoleMode.CursorRow = (INT32)y;
    return EFI_SUCCESS;
}
static EFI_STATUS display_console_cursor_enable(EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *self, UINT8 enabled) {
    (void)self;
    gDisplayConsoleMode.CursorVisible = enabled;
    return EFI_SUCCESS;
}
static EFI_STATUS display_console_clear(EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *self) {
    (void)self;
    EFI_GRAPHICS_OUTPUT_BLT_PIXEL background = display_pixel((UINTN)gDisplayConsoleMode.Attribute >> 4);
    gDisplayConsoleMode.CursorColumn = gDisplayConsoleMode.CursorRow = 0;
    return gSettingsDisplayGop->Blt(gSettingsDisplayGop, &background, 0, 0, 0, 0, 0,
        gSettingsDisplayGop->Mode->Info->HorizontalResolution,
        gSettingsDisplayGop->Mode->Info->VerticalResolution, 0);
}
static EFI_STATUS display_console_set(EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *self, UINTN mode) {
    return mode ? EFI_UNSUPPORTED : display_console_clear(self);
}
static EFI_STATUS display_console_text(EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *self, CHAR16 *text) {
    UINTN columns, rows;
    display_console_query(self, 0, &columns, &rows);
    UINTN width = gSettingsDisplayGop->Mode->Info->HorizontalResolution;
    UINTN top = (gSettingsDisplayGop->Mode->Info->VerticalResolution - rows * NATIVE_FONT_HEIGHT) / 2U;
    EFI_GRAPHICS_OUTPUT_BLT_PIXEL foreground = display_pixel((UINTN)gDisplayConsoleMode.Attribute);
    EFI_GRAPHICS_OUTPUT_BLT_PIXEL background = display_pixel((UINTN)gDisplayConsoleMode.Attribute >> 4);
    while (*text) {
        CHAR16 ch = *text++;
        if (ch == '\r') { gDisplayConsoleMode.CursorColumn = 0; continue; }
        if (ch == 8) { if (gDisplayConsoleMode.CursorColumn) gDisplayConsoleMode.CursorColumn--; continue; }
        if (ch == '\n') gDisplayConsoleMode.CursorRow++;
        else {
            EFI_GRAPHICS_OUTPUT_BLT_PIXEL glyph[NATIVE_FONT_WIDTH * NATIVE_FONT_HEIGHT];
            if (ch < 32 || ch > 126) ch = '?';
            for (UINTN y = 0; y < NATIVE_FONT_HEIGHT; y++) for (UINTN x = 0; x < NATIVE_FONT_WIDTH; x++)
                glyph[y * NATIVE_FONT_WIDTH + x] = native_font[ch - 32][y] & (0x80U >> x) ? foreground : background;
            EFI_STATUS status = gSettingsDisplayGop->Blt(gSettingsDisplayGop, glyph, 2, 0, 0,
                (UINTN)gDisplayConsoleMode.CursorColumn * NATIVE_FONT_WIDTH,
                top + (UINTN)gDisplayConsoleMode.CursorRow * NATIVE_FONT_HEIGHT, NATIVE_FONT_WIDTH, NATIVE_FONT_HEIGHT, 0);
            if (status != EFI_SUCCESS) return status;
            if (++gDisplayConsoleMode.CursorColumn >= (INT32)columns) {
                gDisplayConsoleMode.CursorColumn = 0;
                gDisplayConsoleMode.CursorRow++;
            }
        }
        if (gDisplayConsoleMode.CursorRow >= (INT32)rows) {
            gDisplayConsoleMode.CursorRow = (INT32)rows - 1;
            EFI_STATUS status = gSettingsDisplayGop->Blt(gSettingsDisplayGop, (void *)0, 3, 0, top + NATIVE_FONT_HEIGHT,
                0, top, width, (rows - 1U) * NATIVE_FONT_HEIGHT, 0);
            if (status != EFI_SUCCESS) return status;
            status = gSettingsDisplayGop->Blt(gSettingsDisplayGop, &background, 0, 0, 0,
                0, top + (rows - 1U) * NATIVE_FONT_HEIGHT, width, NATIVE_FONT_HEIGHT, 0);
            if (status != EFI_SUCCESS) return status;
        }
    }
    return EFI_SUCCESS;
}
static void display_console_install(void) {
    gDisplayConsole.OutputString = display_console_text;
    gDisplayConsole.QueryMode = display_console_query;
    gDisplayConsole.SetMode = display_console_set;
    gDisplayConsole.SetAttribute = display_console_attribute;
    gDisplayConsole.ClearScreen = display_console_clear;
    gDisplayConsole.SetCursorPosition = display_console_cursor;
    gDisplayConsole.EnableCursor = display_console_cursor_enable;
    gDisplayConsole.Mode = &gDisplayConsoleMode;
    gDisplaySystemTable = *gST;
    gDisplaySystemTable.ConOut = &gDisplayConsole;
    gST = &gDisplaySystemTable;
}
