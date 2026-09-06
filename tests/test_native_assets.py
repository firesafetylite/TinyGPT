"""Offline asset restoration must preserve user files and protected recovery."""
from pathlib import Path
import importlib.util
import runpy
import struct
import tempfile
import unittest
from bios_fixture import disk_fixture, native_elf

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("native_images", ROOT / "tools/native_image.py")
images = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(images)
Fat = runpy.run_path(str(ROOT / "tinygpt"))["Fat32Image"]
WAD = b"IWAD" + struct.pack("<II", 1, 16) + b"DATA" + struct.pack("<II8s", 12, 4, b"TEST")


class NativeAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="tinygpt-assets-")
        cls.disk = disk_fixture(Path(cls.temporary.name)).read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()
        del cls.disk

    def missing_asset(self):
        fat = Fat(self.disk, partition_index=1)
        offset, entry = fat._find_entry((images.DOOM_NAME,))
        for cluster in fat._chain(fat._entry_cluster(entry)):
            fat._fat_set(cluster, 0)
        fat.data[offset] = 0xE5
        return fat

    def test_missing_wad_is_restored_without_touching_recovery_or_other_files(self):
        fat = self.missing_asset()
        before = bytes(fat.data)
        old_files = {entry[:11]: fat.read_file((entry[:11],))
                     for _, entry in fat._directory_entries(fat.root_cluster) if not entry[11] & 0x18}
        after = images.install_doom(before, WAD)
        updated = Fat(after, partition_index=1)
        self.assertEqual(updated.read_file((images.DOOM_NAME,)), WAD)
        start = fat.volume_offset
        end = start + fat.total_sectors * 512
        self.assertEqual(after[:start], before[:start])
        self.assertEqual(after[end:], before[end:])
        for name, payload in old_files.items():
            self.assertEqual(updated.read_file((name,)), payload)

    def test_existing_wad_and_game_configuration_are_not_replaced(self):
        # Even a customized or unrecognized existing WAD is not overwritten.
        self.assertEqual(images.install_doom(self.disk, WAD), self.disk)
        fat = self.missing_asset()
        with_config = images._install_root_file(bytes(fat.data), b"custom binds\n", b"DOOM    CFG", 2)
        with_save = images._install_root_file(with_config, b"saved game", b"DOOMSAV0DSG", 2)
        after = images.install_doom(with_save, WAD)
        updated = Fat(after, partition_index=1)
        self.assertEqual(updated.read_file((b"DOOM    CFG",)), b"custom binds\n")
        self.assertEqual(updated.read_file((b"DOOMSAV0DSG",)), b"saved game")
        self.assertEqual(images.install_doom(after, WAD), after)

    def test_full_root_grows_and_native_system_still_installs(self):
        fat = self.missing_asset()
        entries = {}
        for cluster in fat._chain(fat.root_cluster):
            base = fat._cluster_offset(cluster)
            for relative in range(0, fat.cluster_bytes, 32):
                offset = base + relative
                if fat.data[offset] in (0, 0xE5):
                    entry = bytearray(32)
                    entry[:11] = f"F{relative // 32:07d}DAT".encode()
                    entry[11] = 0x20
                    fat.data[offset:offset+32] = entry
                entry = bytes(fat.data[offset:offset+32])
                if entry[11] != 0x0F:
                    entries[entry[:11]] = entry
        old_chain = fat._chain(fat.root_cluster)
        restored = images.install_doom(bytes(fat.data), WAD)
        elf = native_elf() + b"TinyGPTNativeABI=4\n"
        updated = Fat(images.install_system(restored, elf), partition_index=1)
        self.assertGreater(len(updated._chain(updated.root_cluster)), len(old_chain))
        self.assertEqual(updated.read_file((images.DOOM_NAME,)), WAD)
        self.assertEqual(updated.read_file((images.NATIVE_NAME,)), elf)
        for name, entry in entries.items():
            self.assertEqual(updated._find_entry((name,))[1], entry)

    def test_bad_assets_and_recovery_targets_are_rejected(self):
        for bad in (b"", b"not an IWAD", b"PWAD" + WAD[4:], WAD[:20], b"IWAD" + struct.pack("<II", 0xFFFFFFFF, 16)):
            with self.assertRaises(ValueError):
                images.install_doom(self.disk, bad)
        for partition in (0, 1, 17):
            with self.assertRaises(ValueError):
                images.install_doom(self.disk, WAD, partition)


if __name__ == "__main__":
    unittest.main()
