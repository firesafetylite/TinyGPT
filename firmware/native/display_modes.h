#ifndef TINYGPT_NATIVE_DISPLAY_MODES_H
#define TINYGPT_NATIVE_DISPLAY_MODES_H
/* RAMFB occupies [0x40400000, 0x40900000); the firmware heap starts at its end. */
#define NATIVE_FRAMEBUFFER_ADDRESS 0x40400000UL
#define NATIVE_FRAMEBUFFER_BYTES (5U * 1024U * 1024U)
static const struct { unsigned width, height; } native_display_modes[] = {
    {640, 480}, {800, 600}, {1024, 768}, {1280, 720}
};
#define NATIVE_DISPLAY_MODE_COUNT (sizeof(native_display_modes) / sizeof(native_display_modes[0]))
static int native_display_mode(unsigned width, unsigned height) {
    for (unsigned i = 0; i < NATIVE_DISPLAY_MODE_COUNT; i++)
        if (native_display_modes[i].width == width && native_display_modes[i].height == height &&
            (unsigned long long)width * height * 4U <= NATIVE_FRAMEBUFFER_BYTES) return (int)i;
    return -1;
}
#endif
