# TinyGPT nightly — native BIOS + OS

This archive is for TinyGPT's own ARM64 BIOS, **not UEFI/EDK II**.
Use all components from the same archive. `manifest.json` records the source
commit, native ABI, sizes and SHA-256 hashes; `SHA256SUMS` covers its files.
Verify the archive against the nightly release's outer `SHA256SUMS` as well.
These checks detect mismatched/corrupt downloads; they are not secure boot.

## Included files

- `TinyGPT-BIOS.bin`: complete 64 MiB native BIOS, with matching recovery OS.
- `TINYGPT.ELF`: OS to install on the system partition of an existing native disk.
- `TinyGPT-factory.img`: 128 MiB **blank factory disk for NEW VMs ONLY**.
- `licenses/`: redistribution notices for TinyGPT, FatFs, font, Doom and Freedoom.

**Never replace an existing user's disk with `TinyGPT-factory.img`: doing so
would discard their files and accounts.** Native guest `update` is not implemented;
this archive does not enable networking or automatic in-guest firmware updates.
Do not use `TinyGPT-nightly.img`, the EFI updater, or `BOOTAA64.EFI` on a native VM.

## New VM

Use QEMU/UTM ARM64 emulation, Cortex-A53, one CPU, 256 MiB RAM, no UEFI,
`virt,secure=off,virtualization=off`, modern VirtIO-MMIO block/keyboard and RAMFB.
For a standalone QEMU installation, after extracting this archive:

```sh
cp TinyGPT-factory.img TinyGPT-user.img
qemu-system-aarch64 \
  -machine virt,secure=off,virtualization=off -cpu cortex-a53 -accel tcg \
  -m 256M -smp 1 -bios TinyGPT-BIOS.bin \
  -global virtio-mmio.force-legacy=false \
  -drive file=TinyGPT-user.img,if=none,id=disk,format=raw \
  -device virtio-blk-device,drive=disk -device ramfb \
  -device virtio-keyboard-device -serial stdio
```

On first boot, create your Administrator account. Run `settings` for the boot
timer, screen resolution and other preferences.

## Existing native VM

1. Run `shutdown` inside the OS; verify the emulator is stopped, not suspended.
2. Make and verify a full backup of the VM, including configuration, BIOS and disk.
3. From the source checkout at the commit in `manifest.json`, use
   `tools/native_image.py`'s `validate_pair(bios_bytes, elf_bytes)` and
   `install_system(disk_bytes, elf_bytes, partition=2)` helpers to prepare a
   **separate updated disk**. They return bytes and do not edit the running VM.
   Use the actual system partition if it is not partition 2. Preserve recovery,
   accounts and all existing user files. The script's normal CLI creates a factory
   disk; it is NOT an in-place updater.
4. With the VM still stopped, install the prepared disk AND this archive's BIOS.
   Verify read-back and boot before discarding any backup. Do not mix ABI versions.

Detailed UTM configuration and migration limits:
https://github.com/firesafetylite/TinyGPT/blob/nightly/firmware/native/README.md
Source and licenses: https://github.com/firesafetylite/TinyGPT
