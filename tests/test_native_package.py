"""Release bundles must bind native BIOS/OS and never publish a user's disk."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from bios_fixture import native_elf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import native_image
import package_native


class NativePackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="tinygpt-native-package-")
        cls.root = Path(cls.temporary.name)
        cls.elf = native_elf() + f"TinyGPTNativeABI={native_image.NATIVE_ABI}\n".encode()
        cls.bios = cls.elf.ljust(native_image.BIOS_BYTES, b"\xff")
        (cls.root / "TINYGPT.ELF").write_bytes(cls.elf)
        (cls.root / "TinyGPT-BIOS.bin").write_bytes(cls.bios)
        native_image.build_image(cls.root / "TINYGPT.ELF", cls.root / "TinyGPT.img")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()
        del cls.bios

    def test_matching_pair_and_truncated_or_mixed_firmware(self):
        native_image.validate_pair(self.bios, self.elf)
        for bios, elf in ((self.bios[:-1], self.elf), (bytes(native_image.BIOS_BYTES), self.elf),
                          (self.bios, self.elf + b"different-build"), (self.bios, b"MZ-not-native")):
            with self.assertRaises(ValueError):
                native_image.validate_pair(bios, elf)

    def test_bundle_contents_checksums_and_no_overwrite(self):
        output = self.root / "native.zip"
        revision = "0123456789abcdef" * 2 + "01234567"
        package_native.package(self.root, output, revision)
        with zipfile.ZipFile(output) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["source_commit"], revision)
            self.assertEqual(manifest["native_abi"], native_image.NATIVE_ABI)
            self.assertEqual(archive.read("TINYGPT.ELF"), self.elf)
            self.assertEqual(archive.read("TinyGPT-BIOS.bin"), self.bios)
            self.assertIn("TinyGPT-factory.img", archive.namelist())
            self.assertNotIn("TinyGPT.img", archive.namelist())
            self.assertIn(b"NEW VMs ONLY", archive.read("README.md"))
            self.assertIn("licenses/FatFs-LICENSE.txt", manifest["files"])
            for name, expected in manifest["files"].items():
                data = archive.read(name)
                self.assertEqual(len(data), expected["size"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), expected["sha256"])
            for line in archive.read("SHA256SUMS").decode().splitlines():
                checksum, name = line.split("  ", 1)
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), checksum)
        with self.assertRaises(FileExistsError):
            package_native.package(self.root, output, revision)
        with self.assertRaises(ValueError):
            package_native.package(self.root, self.root / "invalid.zip", "nightly")
        self.assertFalse((self.root / "invalid.zip").exists())

    def test_user_files_or_mismatched_disk_prevent_packaging(self):
        path = self.root / "TinyGPT.img"
        clean = path.read_bytes()
        try:
            for changed in (
                native_image.install_system(clean, self.elf + b"another-build"),
                native_image._install_root_file(clean, b"private document", b"PRIVATE TXT", 2),
            ):
                path.write_bytes(changed)
                output = self.root / "rejected.zip"
                with self.assertRaises(ValueError):
                    package_native.package(self.root, output, "a" * 40)
                self.assertFalse(output.exists())
        finally:
            path.write_bytes(clean)

    def test_nightly_preserves_efi_and_gates_native_publication(self):
        workflow = (ROOT / ".github/workflows/nightly.yml").read_text()
        for required in ("make native", "python tools/test_native.py", "python tools/test_settings.py",
                         "python tools/package_native.py", "TinyGPT-nightly-native.zip",
                         "TinyGPT-nightly.img", "TinyGPT-nightly-BOOTAA64.EFI"):
            self.assertIn(required, workflow)
        self.assertLess(workflow.index("python tools/test_settings.py"), workflow.index("gh release upload"))
        self.assertLess(workflow.index("python tools/package_native.py"), workflow.index("sha256sum TinyGPT-*"))


if __name__ == "__main__":
    unittest.main()
