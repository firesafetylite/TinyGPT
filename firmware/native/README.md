# TinyGPT native firmware and system

This target boots the real TinyGPT application without EDK II, an EFI executable,
or UEFI firmware services. TinyGPT-owned adapters implement the subset of the
old interface-shaped C types that the shared application uses. These are not a
general UEFI implementation. `firmware/bios` also retains its smaller read-only
bring-up target; that target is not this full system.

## Build and validate

Requires Zig 0.14.1 (`pip install ziglang==0.14.1`), Python, and QEMU for tests:

```sh
make native
QEMU_AARCH64=qemu-system-aarch64 make native-test
make test
```

Outputs in `build/native`:

- `TinyGPT-BIOS.bin`: 64 MiB flash image, with independent firmware recovery and
  embedded copies of the native system and Freedoom IWAD for explicitly authorized repair.
- `TINYGPT.ELF`: separately disk-loaded OS, native ABI 4 (adds the display-mode callback; update matching BIOS and ELF together).
- `TinyGPT.img`: new 128 MiB GPT/FAT disk. Do **not** replace an existing user disk
  with this factory image.

The BIOS validates ELF load ranges and ABI, loads `TINYGPT.ELF` from the selected
system partition, and passes TinyGPT-owned hardware callbacks. Native memory is
identity-mapped: flash/RAM use Normal non-cacheable memory (needed for packed
Doom records), while MMIO uses Device memory. This is not process isolation. Esc/R during
startup enters firmware recovery. Missing system files no longer silently
regenerate during startup; administrator-authorized repair restores them. Repair
also restores missing `DOOMU.WAD` from the BIOS, through a staged file with exact
length/SHA-256 read-back before publication. Existing IWADs, saves and game settings
are not overwritten. Restoring the game requires about 28 MiB of free disk space;
normal boot and the `doom` command do not silently undo an OS wipe.

Tested platform (do not blindly swap an existing UTM PFlash):

```sh
qemu-system-aarch64 \
  -machine virt,secure=off,virtualization=off -cpu cortex-a53 -accel tcg \
  -m 256M -smp 1 -bios build/native/TinyGPT-BIOS.bin \
  -global virtio-mmio.force-legacy=false \
  -drive file=build/native/TinyGPT.img,if=none,id=disk,format=raw \
  -device virtio-blk-device,drive=disk -device ramfb \
  -device virtio-keyboard-device -serial stdio
```

The graphical text console defaults to 640×480 with an 80×25 terminal using the
original 8×19 console font (unscaled glyph rows); UART is available in parallel.
**Settings > 10 — Screen resolution** also offers 800×600 (100×31), 1024×768
(128×40), and 1280×720 (160×37). Preview changes revert after 15 seconds unless
confirmed with Y; confirmed dimensions persist on the system partition. Recovery
always starts at the safe 640×480 mode. RAMFB is bounded to its reserved 5 MiB
region, never the firmware heap. **Settings > 9 — Auto boot timer** changes the
global startup recovery-key window to 1–60 seconds, with administrator approval.
Holding
an arrow starts navigation/scrollback repeat after 400 ms, then repeats at 20 Hz.
Queued releases are processed before any repeat; printable keys are not synthesized. Graphics output for application code is supplied through the native
framebuffer adapter. Keyboard input uses modern VirtIO-MMIO. This target does
not drive VirtIO PCI storage, USB keyboards, or the old virtio-ramfb PCI setup.

Writable block access requires negotiated flush support. FatFs provides FAT16/
FAT32 and long filenames; the shared application retains its direct-file journal,
mirrored GPT checks, protected recovery partition, account database, permissions,
Settings, and editor. The memory layout requires 256 MiB RAM, one CPU, and the
specified QEMU board. No MMU isolation or verified boot is provided.

`tools/test_native.py` boots only a disposable disk and exercises actual native
boot, setup/login, Settings account creation, persistent writes, graphics and
VirtIO keyboard input, custom-colored scrollback, missing-system recovery,
authenticated repair, standard-user denial, root wipe, reboot, and shutdown.
After wiping and repairing, it launches the restored Doom, checks for an actual
rendered game frame, and exits back to the shell. Extended manual gameplay and
real UTM migration remain separate validations. Neither test nor builder edits
the real VM. `python3 tools/test_settings.py --qemu qemu-system-aarch64` separately
checks timer validation, reboot persistence and the recovery-key window, all four
resolution previews, confirmation, timeout/explicit rollback, and boot-default
restoration on a disposable disk.

## Matched nightly download

The rolling nightly release includes `TinyGPT-nightly-native.zip`. It packages
BIOS and ELF from the same build with a new-VM-only factory disk, licenses,
installation notes, per-file checksums, and a source-commit/ABI manifest. The
packager verifies that the ROM embeds the exact ELF and that the clean factory
disk contains it, refusing unexpected account/user files. The nightly workflow
runs both native VM suites before publishing. Verify the archive against the
release's outer `SHA256SUMS`, then use the bundled `README.md`.

See [distribution/install instructions](DISTRIBUTION.md). The separate
`TinyGPT-nightly.img` and EFI update manifests are **not** native updates.

## Migration safety and remaining limitations

Stop the guest cleanly and make a fresh **complete VM backup** before changing
configuration, flash, or disk. Install matching BIOS and ELF artifacts together;
`tools/native_image.py:install_system` can prepare an updated disk in memory while
verifying that bytes outside the selected system partition remain unchanged.
`tools/native_image.py:install_doom` separately restores a missing IWAD without
replacing an existing one. Preserve existing data and recovery/accounts, and verify
disk read-back before starting the converted VM. Remove EDK II and variable-store drives from the active
boot configuration, disable automatic UEFI firmware, and use the hardware above.
Retain the complete old VM backup for rollback.

Native guest HTTP/TLS and guest-downloaded upgrades are not implemented. Native
builds reject EFI update payloads; use paired host-built firmware/system updates.
The legacy EFI artifacts remain available for existing EFI installations;
nightly publishes the native bundle separately and never puts ELF into the EFI
update manifest. Account salts use the
existing non-cryptographic fallback because the native platform has no RNG
protocol yet; local authentication is not disk encryption or offline tamper
protection. FAT and account redundancy do not guarantee arbitrary power-loss
atomicity. Native payloads and firmware are privileged and not sandboxed.

Third-party source retains its notices: FatFs R0.16 from
https://elm-chan.org/fsw/ff/ (writable FAT, LFN, CP437; named volume limit extended
from 10 to 16), and the original 8×19 font bitmaps under BSD-2-Clause-Patent
([font provenance and license](../../third_party/console-font/README.md)). Only
font data is reused, not EDK II firmware code or services. The binary font notice
is copied to `build/native/CONSOLE-FONT-LICENSE.txt`. Existing PureDOOM/Freedoom
licenses remain applicable to the shared game code/assets. The BIOS now embeds
Freedoom assets; distribute `build/native/FREEDOOM-COPYING.txt` with it.
