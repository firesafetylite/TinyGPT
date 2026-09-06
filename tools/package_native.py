#!/usr/bin/env python3
"""Publish one validated native BIOS/OS/factory-disk bundle, separate from EFI."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import zipfile

from native_image import NATIVE_ABI, NATIVE_NAME, ROOT, validate_pair


def package(build: Path, output: Path, revision: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("A full source commit SHA is required")
    bios = (build / "TinyGPT-BIOS.bin").read_bytes()
    system = (build / "TINYGPT.ELF").read_bytes()
    disk = (build / "TinyGPT.img").read_bytes()
    validate_pair(bios, system)
    if len(disk) != 128 * 1024 * 1024:
        raise ValueError("Expected the complete 128 MiB native factory disk")
    fat_type = runpy.run_path(str(ROOT / "tinygpt"))["Fat32Image"]
    installed = fat_type(disk, partition_index=1)
    if installed.read_file((NATIVE_NAME,)) != system:
        raise ValueError("Factory disk contains a different native OS")
    if installed.read_file((b"TINYGPT NEW",)) != b"Initialize TinyGPT on first boot\n":
        raise ValueError("Only a fresh factory disk may be published")
    recovery = fat_type(disk)
    if recovery.read_file((b"NATIVE  TXT",)) != b"Boot with TinyGPT BIOS, not EDK II. The system is TINYGPT.ELF on partition 2.\n":
        raise ValueError("Factory disk is not marked as native")
    # Do not accidentally publish accounts or a user's filesystem as a factory disk.
    def names(volume, directory):
        return {entry[:11] for _, entry in volume._directory_entries(directory)
                if not entry[11] & 8 and entry[:1] != b"."}
    if names(installed, installed.root_cluster) != {NATIVE_NAME, b"DOOMU   WAD", b"TINYGPT NEW"}:
        raise ValueError("Factory system partition contains unexpected files")
    if names(recovery, recovery.root_cluster) != {b"EFI        ", b"NATIVE  TXT"}:
        raise ValueError("Factory recovery partition contains unexpected files")
    _, efi = recovery._find_entry((b"EFI        ",))
    _, boot = recovery._find_entry((b"EFI        ", b"BOOT       "))
    if (names(recovery, recovery._entry_cluster(efi)) != {b"BOOT       "} or
            names(recovery, recovery._entry_cluster(boot)) != {b"RECOVERYELF"} or
            recovery.read_file((b"EFI        ", b"BOOT       ", b"RECOVERYELF")) != system):
        raise ValueError("Factory recovery payload does not match the native OS")
    files = {
        "TinyGPT-BIOS.bin": bios,
        "TINYGPT.ELF": system,
        "TinyGPT-factory.img": disk,
        "README.md": (ROOT / "firmware/native/DISTRIBUTION.md").read_bytes(),
    }
    notices = {
        "TinyGPT-LICENSE.txt": "LICENSE",
        "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.md",
        "CONSOLE-FONT-LICENSE.txt": "third_party/console-font/LICENSE.txt",
        "PureDOOM-LICENSE.txt": "third_party/PureDOOM/LICENSE",
        "FREEDOOM-COPYING.txt": "assets/FREEDOOM-COPYING.txt",
        "FREEDOOM-CREDITS.txt": "assets/FREEDOOM-CREDITS.txt",
        "FREEDOOM-CREDITS-MUSIC.txt": "assets/FREEDOOM-CREDITS-MUSIC.txt",
        "FREEDOOM-README.html": "assets/FREEDOOM-README.html",
    }
    for name, source in notices.items():
        files["licenses/" + name] = (ROOT / source).read_bytes()
    # Preserve FatFs's verbatim embedded notice (it has no separate license file).
    fatfs = (ROOT / "third_party/FatFs/ff.c").read_bytes()
    files["licenses/FatFs-LICENSE.txt"] = fatfs[:fatfs.index(b"*/") + 2] + b"\n"
    manifest = {
        "format": 1,
        "architecture": "aarch64",
        "channel": "nightly",
        "native_abi": NATIVE_ABI,
        "source_commit": revision,
        "files": {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in sorted(files.items())},
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    files["SHA256SUMS"] = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n"
                                   for name, data in sorted(files.items())).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidentally replacing a disk or previous bundle.
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    with zipfile.ZipFile(output) as archive:
        for name, data in files.items():
            if archive.read(name) != data:
                raise ValueError(f"Archive read-back mismatch: {name}")
    print(f"Packaged native ABI {NATIVE_ABI} BIOS/OS pair at {revision}: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build/native")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    package(args.build, args.output, args.revision)
