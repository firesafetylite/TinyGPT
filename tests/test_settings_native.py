"""Execute production preference parsers, persistence and graphics on host models."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src/uefi.c").read_text()
TYPES = SOURCE.split("static EFI_SYSTEM_TABLE *gST;", 1)[0]


def block(start, end):
    return start + SOURCE.split(start, 1)[1].split(end, 1)[0]


class SettingsNativeTests(unittest.TestCase):
    def run_c(self, source):
        compiler = shutil.which("cc")
        if not compiler:
            self.skipTest("Requires a host C compiler")
        with tempfile.TemporaryDirectory(prefix="tinygpt-settings-unit-") as directory:
            path = Path(directory)
            (path / "test.c").write_text('#include <assert.h>\n#include <stdlib.h>\n#include <string.h>\n' + TYPES + source)
            result = subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                                     "-Wno-unused-function", "-Wno-unused-variable", "-I", str(ROOT),
                                     str(path / "test.c"), "-o", str(path / "test")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(path / "test")], check=True, timeout=10)

    def test_boot_timer_validation_and_failed_storage(self):
        helpers = block("static void memory_copy(", "static void out16(")
        self.run_c(helpers + r'''
static EFI_FILE_PROTOCOL *gBootVolumeRoot;
static EFI_GUID gFileInfoGuid;
static UINT8 disk[64];
static UINTN length, position;
static int exists, fail_read, fail_write, fail_flush, fail_close, fail_size;
static EFI_FILE_PROTOCOL file;
static EFI_STATUS open_file(EFI_FILE_PROTOCOL *self, EFI_FILE_PROTOCOL **out, CHAR16 *path, UINT64 mode, UINT64 attr) {
    (void)self; (void)path; (void)attr; *out=0;
    if (!exists && !(mode & EFI_FILE_MODE_CREATE)) return EFI_NOT_FOUND;
    exists=1; position=0; *out=&file; return EFI_SUCCESS;
}
static EFI_STATUS close_file(EFI_FILE_PROTOCOL *self) { (void)self; return fail_close ? EFI_DEVICE_ERROR : EFI_SUCCESS; }
static EFI_STATUS seek_file(EFI_FILE_PROTOCOL *self, UINT64 offset) { (void)self; position=offset; return EFI_SUCCESS; }
static EFI_STATUS read_file(EFI_FILE_PROTOCOL *self, UINTN *bytes, void *out) {
    (void)self; if (fail_read) return EFI_DEVICE_ERROR;
    if (*bytes>length-position) *bytes=length-position;
    memcpy(out,disk+position,*bytes); position+=*bytes; return EFI_SUCCESS;
}
static EFI_STATUS write_file(EFI_FILE_PROTOCOL *self, UINTN *bytes, void *data) {
    (void)self; if (fail_write) { *bytes=0; return EFI_DEVICE_ERROR; }
    assert(position+*bytes<=sizeof(disk)); memcpy(disk+position,data,*bytes); position+=*bytes;
    if (position>length) length=position; return EFI_SUCCESS;
}
static EFI_STATUS get_info(EFI_FILE_PROTOCOL *self, EFI_GUID *guid, UINTN *bytes, void *buffer) {
    (void)self; (void)guid; EFI_FILE_INFO *info=buffer;
    assert(*bytes>=sizeof(*info)); memset(info,0,sizeof(*info)); info->Size=*bytes=sizeof(*info); info->FileSize=length;
    return EFI_SUCCESS;
}
static EFI_STATUS set_info(EFI_FILE_PROTOCOL *self, EFI_GUID *guid, UINTN bytes, void *buffer) {
    (void)self; (void)guid; (void)bytes; if (fail_size) return EFI_DEVICE_ERROR;
    length=((EFI_FILE_INFO *)buffer)->FileSize; return EFI_SUCCESS;
}
static EFI_STATUS flush_file(EFI_FILE_PROTOCOL *self) { (void)self; return fail_flush ? EFI_DEVICE_ERROR : EFI_SUCCESS; }
#include "src/boot_settings.inc"
int main(void) {
    file=(EFI_FILE_PROTOCOL){0,open_file,close_file,0,read_file,write_file,0,seek_file,get_info,set_info,flush_file};
    assert(boot_settings_seconds()==2 && !boot_settings_save(5));
    gBootVolumeRoot=&file;
    assert(boot_settings_seconds()==2);
    assert(!boot_settings_save(0) && !boot_settings_save(61) && !boot_settings_save(0xffffffffU));
    assert(boot_settings_save(1) && boot_settings_seconds()==1);
    assert(boot_settings_save(60) && boot_settings_seconds()==60);
    UINT8 saved[sizeof(disk)]; memcpy(saved,disk,sizeof(disk));
    for (UINTN i=0;i<sizeof(BOOT_SETTINGS_RECORD);i++) {
        disk[i]^=1; assert(boot_settings_seconds()==2); memcpy(disk,saved,sizeof(disk));
    }
    length--; assert(boot_settings_seconds()==2);
    length+=2; assert(boot_settings_seconds()==2);
    assert(boot_settings_save(5) && length==sizeof(BOOT_SETTINGS_RECORD));
    fail_read=1; assert(boot_settings_seconds()==2 && !boot_settings_save(7)); fail_read=0;
    fail_write=1; assert(!boot_settings_save(7)); fail_write=0;
    fail_flush=1; assert(!boot_settings_save(7)); fail_flush=0;
    fail_close=1; assert(!boot_settings_save(7)); fail_close=0;
    fail_size=1; assert(!boot_settings_save(7)); fail_size=0;
    assert(boot_settings_save(2) && boot_settings_seconds()==2);
    return 0;
}
''')

    def test_settings_round_trip_and_malformed_dimensions(self):
        settings_type = "typedef struct {\n    UINT8 textColor;" + SOURCE.split("typedef struct {\n    UINT8 textColor;", 1)[1].split("static void settings_use_default_color", 1)[0]
        helpers = block("static UINTN string_length(", "static char *skip_spaces(")
        settings = block("static int settings_parse_uint32(", "static void settings_apply_runtime(")
        self.run_c(settings_type + r'''
static EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL console;
static EFI_SYSTEM_TABLE table, *gST=&table;
static UINT8 gConsoleColorRole, gStorageReady=1;
static char gFileBuffer[FS_DATA_BYTES], persisted[FS_DATA_BYTES];
static struct { int type; } gNodes[2]={{FS_FILE},{FS_DIRECTORY}};
static int fs_resolve(const char *path) { return strcmp(path,"/home") ? 0 : 1; }
static int fs_alloc(int type, UINTN parent, const char *name, int flags) { (void)type;(void)parent;(void)name;(void)flags;return 0; }
static int storage_read_node(UINTN node, char *buffer, UINTN capacity, UINTN *length) {
    (void)node; *length=strlen(persisted); assert(*length<capacity); memcpy(buffer,persisted,*length); return 1;
}
static int fs_set_file(UINTN node, const char *data) { (void)node; strcpy(persisted,data); return 1; }
''' + helpers + settings + r'''
int main(void) {
    table.ConOut=&console;
    UINT32 value=99; UINT8 byte=99;
    assert(settings_parse_uint32("4294967295",&value) && value==0xffffffffU);
    assert(!settings_parse_uint32("4294967296",&value));
    assert(!settings_parse_uint32("99999999999999999999999999999999999",&value));
    assert(!settings_parse_uint32("",&value) && !settings_parse_uint32("-1",&value));
    assert(!settings_parse_uint32(" 800",&value) && !settings_parse_uint32("800x600",&value));
    assert(settings_parse_uint8("255",&byte) && byte==255 && !settings_parse_uint8("256",&byte));
    settings_defaults(); assert(!gSettings.displayWidth && !gSettings.displayHeight);
    gSettings.textColor=12; gSettings.accentColor=10; gSettings.backgroundColor=1;
    gSettings.displayWidth=1280; gSettings.displayHeight=720;
    assert(settings_save());
    assert(strstr(persisted,"display_width=1280\ndisplay_height=720\n"));
    settings_load();
    assert(gSettings.displayWidth==1280 && gSettings.displayHeight==720);
    assert(gSettings.textColor==12 && gSettings.accentColor==10 && gSettings.backgroundColor==1);
    strcpy(persisted,"display_width=800\n"); settings_load();
    assert(!gSettings.displayWidth && !gSettings.displayHeight);
    strcpy(persisted,"display_width=4294967296800\ndisplay_height=600\n"); settings_load();
    assert(!gSettings.displayWidth && !gSettings.displayHeight);
    strcpy(persisted,"display_width=1\ndisplay_height=99999\ntext_color=11\n"); settings_load();
    assert(!gSettings.displayWidth && !gSettings.displayHeight && gSettings.textColor==11);
    strcpy(persisted,"text_color=12\naccent_color=10\n"); settings_load(); /* Old config remains valid. */
    assert(gSettings.textColor==12 && !gSettings.displayWidth);
    strcpy(persisted,"display_width=1920\r\ndisplay_height=1080\r\nunknown=7\n"); settings_load();
    assert(gSettings.displayWidth==1920 && gSettings.displayHeight==1080);
    gStorageReady=0; assert(!settings_save());
    return 0;
}
''')

    def test_uefi_console_preview_confirmation_timeout_and_failure(self):
        display = (ROOT / "src/display_settings.inc").read_text().replace('__asm__ volatile("yield");', ';')
        display = display.replace('#include "display_console.inc"', '#include "src/display_console.inc"')
        self.run_c(r'''
static EFI_SYSTEM_TABLE table, *gST=&table;
static EFI_BOOT_SERVICES_PREFIX services;
static EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL original_console;
static EFI_GRAPHICS_OUTPUT_PROTOCOL gop;
static EFI_GRAPHICS_OUTPUT_MODE_INFORMATION info;
static EFI_GRAPHICS_OUTPUT_PROTOCOL_MODE mode;
static struct { UINT32 displayWidth,displayHeight; } gSettings;
static UINT64 gTimerHz=1000, clock_ticks;
static int confirmation, fail_mode=-1, saves, allocations;
static const char *answer="0";
static UINTN columns,rows;
static UINT32 pixels[1024*768+2];
static const UINT32 sizes[][2]={{640,480},{800,600},{1024,768},{320,200}};
static int streq(const char *a, const char *b) { return !strcmp(a,b); }
static int settings_parse_uint32(const char *text, UINT32 *out) {
    char *end; unsigned long n=strtoul(text,&end,10); if (!*text || *end || n>0xffffffffU) return 0; *out=(UINT32)n; return 1;
}
static void print(const char *text) { (void)text; }
static void print_u64(UINT64 value) { (void)value; }
static void read_line(char *out, UINTN capacity) { assert(strlen(answer)<capacity); strcpy(out,answer); }
static UINT64 timer_count(void) { clock_ticks+=10000; return clock_ticks; }
static int poll_input_key(EFI_INPUT_KEY *key) {
    if (!confirmation) return 0; key->ScanCode=0; key->UnicodeChar=(CHAR16)confirmation; confirmation=0; return 1;
}
static const char *settings_save_notice(void) { saves++; return "saved"; }
static void settings_use_default_color(void) { gST->ConOut->SetAttribute(gST->ConOut,0x1c); }
static void console_update_geometry(void) { assert(gST->ConOut->QueryMode(gST->ConOut,0,&columns,&rows)==EFI_SUCCESS); }
static void scrollback_reset(void) {}
static EFI_STATUS query(EFI_GRAPHICS_OUTPUT_PROTOCOL *self, UINT32 number, UINTN *bytes, EFI_GRAPHICS_OUTPUT_MODE_INFORMATION **out) {
    (void)self; *out=0; if (number>=4) return EFI_UNSUPPORTED;
    *out=malloc(sizeof(**out)); allocations++; **out=info;
    (*out)->HorizontalResolution=sizes[number][0]; (*out)->VerticalResolution=sizes[number][1];
    *bytes=sizeof(**out); return EFI_SUCCESS;
}
static EFI_STATUS release(void *pointer) { free(pointer); allocations--; return EFI_SUCCESS; }
static EFI_STATUS set(EFI_GRAPHICS_OUTPUT_PROTOCOL *self, UINT32 number) {
    (void)self; if (number>=4 || (int)number==fail_mode) return EFI_DEVICE_ERROR;
    mode.Mode=number; info.HorizontalResolution=sizes[number][0]; info.VerticalResolution=sizes[number][1]; return EFI_SUCCESS;
}
static EFI_STATUS locate(EFI_GUID *guid, void *registration, void **out) { (void)guid;(void)registration;*out=&gop;return EFI_SUCCESS; }
static EFI_STATUS handle(EFI_HANDLE h, EFI_GUID *guid, void **out) { (void)h;(void)guid;*out=0;return EFI_NOT_FOUND; }
static EFI_STATUS blt(EFI_GRAPHICS_OUTPUT_PROTOCOL *self, EFI_GRAPHICS_OUTPUT_BLT_PIXEL *buffer, UINT32 operation,
    UINTN sx, UINTN sy, UINTN dx, UINTN dy, UINTN width, UINTN height, UINTN delta) {
    (void)self;
    UINTN stride=info.HorizontalResolution;
    assert(dx+width<=stride && dy+height<=info.VerticalResolution);
    if (!delta) delta=width*sizeof(*buffer);
    if (operation==3) {
        assert(sx+width<=stride && sy+height<=info.VerticalResolution);
        for (UINTN y=0;y<height;y++) memmove(pixels+1+(dy+y)*stride+dx,pixels+1+(sy+y)*stride+sx,width*4);
    } else for (UINTN y=0;y<height;y++) for (UINTN x=0;x<width;x++) {
        EFI_GRAPHICS_OUTPUT_BLT_PIXEL p=operation==0 ? *buffer : *(EFI_GRAPHICS_OUTPUT_BLT_PIXEL *)((UINT8 *)buffer+(sy+y)*delta+(sx+x)*sizeof(p));
        pixels[1+(dy+y)*stride+dx+x]=((UINT32)p.Red<<16)|((UINT32)p.Green<<8)|p.Blue;
    }
    return EFI_SUCCESS;
}
''' + display + r'''
int main(void) {
    services.HandleProtocol=handle; services.LocateProtocol=locate; services.FreePool=release;
    table.BootServices=&services; table.ConOut=&original_console;
    mode.MaxMode=4; mode.Info=&info; gop=(EFI_GRAPHICS_OUTPUT_PROTOCOL){query,set,blt,&mode}; set(&gop,0);
    assert(settings_display_load());
    gSettings.displayWidth=999; gSettings.displayHeight=999;
    assert(!settings_display_load() && mode.Mode==0 && !allocations);
    gSettings.displayWidth=1024; gSettings.displayHeight=768;
    assert(settings_display_load() && mode.Mode==2 && columns==128 && rows==40 && !allocations);
    assert(table.ConOut==&original_console); /* Never mutate the firmware's system table. */
    UINTN end=(UINTN)info.HorizontalResolution*info.VerticalResolution;
    pixels[0]=pixels[end+1]=0xdeadbeef;
    CHAR16 letter[]={'F',0}; display_console_text(gST->ConOut,letter);
    assert(pixels[1+(4+3)*1024]==0xff5555); /* Unscaled font, live palette and centered rows. */
    assert(display_console_cursor(gST->ConOut,128,0)==EFI_UNSUPPORTED);
    assert(display_console_cursor(gST->ConOut,127,39)==EFI_SUCCESS);
    display_console_text(gST->ConOut,letter); /* Bottom-right wrapping scrolls within the framebuffer. */
    assert(pixels[0]==0xdeadbeef && pixels[end+1]==0xdeadbeef);
    answer="2"; confirmation='n';
    assert(strstr(settings_choose_display(),"reverted") && mode.Mode==2 && !saves);
    confirmation=0;
    assert(strstr(settings_choose_display(),"reverted") && mode.Mode==2 && !saves); /* Timeout. */
    fail_mode=1;
    assert(strstr(settings_choose_display(),"failed") && mode.Mode==2 && !saves);
    fail_mode=-1; confirmation='y';
    assert(!strcmp(settings_choose_display(),"saved") && mode.Mode==1 && saves==1);
    assert(gSettings.displayWidth==800 && gSettings.displayHeight==600 && columns==100 && rows==31);
    answer="d"; confirmation='y';
    assert(!strcmp(settings_choose_display(),"saved") && mode.Mode==0 && !gSettings.displayWidth && !gSettings.displayHeight);
    answer="4"; assert(strstr(settings_choose_display(),"Invalid") && mode.Mode==0);
    assert(!allocations);
    return 0;
}
''')

    def test_native_all_modes_render_and_reject_unsafe_sizes(self):
        self.run_c(r'''
#include "firmware/native/api.h"
static NativeApi api;
static const NativeApi *native_api=&api;
static EFI_SIMPLE_TEXT_OUTPUT_MODE native_mode;
static int reject;
static EFI_STATUS native_allocate(UINT32 type, UINTN bytes, void **out) {
    (void)type; *out=malloc(bytes); return *out ? EFI_SUCCESS : EFI_OUT_OF_RESOURCES;
}
#include "firmware/native/graphics.inc"
static UINT32 pixels[NATIVE_FRAMEBUFFER_BYTES/4+2];
static int change_display(uint32_t width, uint32_t height) {
    if (reject || native_display_mode(width,height)<0) return 0;
    api.width=width; api.height=height; return 1;
}
int main(void) {
    api.framebuffer=pixels+1; api.width=640; api.height=480; api.set_display=change_display;
    native_mode.Attribute=0x1c; native_graphics_initialize();
    assert(native_gop_mode.MaxMode==4);
    for (unsigned mode=0;mode<NATIVE_DISPLAY_MODE_COUNT;mode++) {
        UINTN bytes=0; EFI_GRAPHICS_OUTPUT_MODE_INFORMATION *info=0;
        assert(native_gop_query(&native_gop,mode,&bytes,&info)==EFI_SUCCESS);
        assert(info->HorizontalResolution==native_display_modes[mode].width);
        free(info);
        UINTN end=(UINTN)native_display_modes[mode].width*native_display_modes[mode].height;
        pixels[0]=pixels[end+1]=0xdeadbeef;
        assert(native_gop_set(&native_gop,mode)==EFI_SUCCESS);
        assert(native_gop_mode.FrameBufferSize==end*4 && native_gop_mode.Mode==mode);
        native_mode.CursorColumn=(INT32)NATIVE_TEXT_COLUMNS-1;
        native_mode.CursorRow=(INT32)NATIVE_TEXT_ROWS-1;
        native_console_character('Z'); native_console_character('\n');
        assert(native_mode.CursorRow==(INT32)NATIVE_TEXT_ROWS-1 && native_mode.CursorColumn==0);
        assert(pixels[0]==0xdeadbeef && pixels[end+1]==0xdeadbeef);
    }
    reject=1; assert(native_gop_set(&native_gop,0)==EFI_DEVICE_ERROR && native_gop_mode.Mode==3);
    assert(native_gop_set(&native_gop,4)==EFI_UNSUPPORTED);
    assert(native_display_mode(1920,1080)<0 && native_display_mode(0,0)<0);
    api.framebuffer=0; assert(native_gop_set(&native_gop,0)==EFI_UNSUPPORTED);
    return 0;
}
''')


if __name__ == "__main__":
    unittest.main()
