#!/usr/bin/env bash
# Builds the disk-loaded OS first, then embeds its authenticated-repair payload in BIOS.
set -euo pipefail
cd "$(dirname "$0")/.."
out=build/native
mkdir -p "$out"
if command -v zig >/dev/null 2>&1; then ZIG=(zig); else ZIG=(python3 -m ziglang); fi
flags=(-target aarch64-freestanding-none -std=c11 -Os -ffreestanding -fno-builtin
  -fno-stack-protector -mgeneral-regs-only -mstrict-align -ffunction-sections -fdata-sections
  -nostdlib -static -Ifirmware/native/include -Wall -Wextra -Werror -Wno-unused-function -Wno-unused-variable -Wno-unknown-pragmas
  '-DTINYGPT_DISPLAY_VERSION="nightly-native"' '-DTINYGPT_BUILD_CHANNEL="nightly"')
"${ZIG[@]}" cc "${flags[@]}" -c third_party/FatFs/ff.c -Ddisk_read=fatfs_disk_read -Ddisk_write=fatfs_disk_write -o "$out/fatfs.o"
"${ZIG[@]}" cc "${flags[@]}" -c third_party/FatFs/ffunicode.c -o "$out/unicode.o"
"${ZIG[@]}" cc "${flags[@]}" firmware/native/runtime.c "$out/fatfs.o" "$out/unicode.o" \
  -Wl,-T,firmware/native/system.ld -Wl,-e,NativeMain -Wl,--gc-sections -Wl,--build-id=none -o "$out/TINYGPT.ELF"
python3 - "$out/TINYGPT.ELF" "$out/system.S" <<'PY'
from pathlib import Path
import hashlib, sys
image, output = map(Path, sys.argv[1:])
wad = Path('assets/freedoom1.wad')
# Zig's assembly cache does not track .incbin inputs: include both payload digests.
assembly = ''
for name, path in [('os', image), ('wad', wad)]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assembly += f'// {name}-sha256: {digest}\n.section .rodata.native_{name},"a"\n.balign 16\n'
    assembly += f'.global native_{name}_start, native_{name}_end\nnative_{name}_start:\n.incbin "{path.resolve()}"\nnative_{name}_end:\n'
output.write_text(assembly)
PY
"${ZIG[@]}" cc "${flags[@]}" -Dbios_main=prototype_main -c firmware/bios/main.c -o "$out/primitives.o"
"${ZIG[@]}" cc "${flags[@]}" -DTINYGPT_FIRMWARE -DTINYGPT_WRITABLE \
  firmware/bios/start.S firmware/native/runtime.c firmware/native/board.c firmware/bios/virtio.c firmware/bios/elf.c \
  "$out/primitives.o" "$out/fatfs.o" "$out/unicode.o" "$out/system.S" \
  -Wl,-T,firmware/bios/link.ld -Wl,--gc-sections -Wl,--build-id=none -o "$out/TinyGPT-BIOS.elf"
python3 tools/make_bios_rom.py "$out/TinyGPT-BIOS.elf" "$out/TinyGPT-BIOS.bin"
python3 - "$out" <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, 'tools')
from native_image import validate_system
out = Path(sys.argv[1])
system = (out / 'TINYGPT.ELF').read_bytes()
validate_system(system)
rom = (out / 'TinyGPT-BIOS.bin').read_bytes()
assert system in rom, 'Recovery ROM contains a stale native system payload'
assert Path('assets/freedoom1.wad').read_bytes() in rom, 'Recovery ROM is missing the Freedoom repair payload'
PY
cp third_party/console-font/LICENSE.txt "$out/CONSOLE-FONT-LICENSE.txt"
cp assets/FREEDOOM-COPYING.txt "$out/FREEDOOM-COPYING.txt"
python3 tools/native_image.py "$out/TINYGPT.ELF" "$out/TinyGPT.img"
ls -lh "$out/TINYGPT.ELF" "$out/TinyGPT-BIOS.bin" "$out/TinyGPT.img"
