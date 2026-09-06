#!/usr/bin/env python3
"""Boot/display Settings regression on a disposable native disk, never a user's VM."""
import argparse
import os
from pathlib import Path
import shutil
import tempfile

from test_native import NativeMachine


def screenshot(machine, directory, name, width, height):
    path = directory / name
    machine.qmp("screendump", {"filename": str(path)})
    assert path.read_bytes().startswith(f"P6\n{width} {height}\n255\n".encode()), name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", default=os.environ.get("QEMU_AARCH64", "qemu-system-aarch64"))
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="tinygpt-settings-") as temporary:
        directory = Path(temporary)
        machine = NativeMachine(directory, args.qemu)
        try:
            machine.wait("Username (1-23 letters, digits, _ or -): ")
            machine.send("tester", "New password (8-64 characters): ")
            machine.send("testpass123", "Repeat password: ")
            machine.send("testpass123")
            menu = machine.send("settings", "Select: ")
            assert "Auto boot timer    : 2 seconds" in menu
            assert "640 x 480 (boot default)" in menu
            machine.send("9", "Seconds: ")
            assert "Invalid timer" in machine.send("61", "Select: ")
            machine.send("9", "Seconds: ")
            assert "canceled" in machine.send("0", "Select: ")
            machine.send("9", "Seconds: ")
            machine.send("5", "Password: ")
            assert "Boot timer saved; applies next boot" in machine.send("testpass123", "Select: ")
            machine.send("10", "Resolution: ")
            assert "Invalid resolution" in machine.send("999", "Select: ")
            modes = machine.send("10", "Resolution: ")
            assert "3  1024 x 768" in modes
            machine.send("3", "Reverting automatically in 15 seconds unless confirmed.")
            screenshot(machine, directory, "preview.ppm", 1024, 768)
            assert "Saved automatically" in machine.send("y", "Select: ")
            machine.send("0")
            config = machine.send("cat /home/.tinygptrc")
            assert "display_width=1024" in config and "display_height=768" in config
            assert "boot_timer" not in config  # Global boot state is on recovery storage.
            # The old hardcoded two-second window would already have expired here.
            machine.send("reboot", "Auto boot in 5 seconds.")
            assert "Username:" not in machine.read_for(3)
            machine.send("r", "preos> ")
            screenshot(machine, directory, "recovery.ppm", 640, 480)
            machine.send("boot 2", "Username: ")
            machine.send("tester", "Password: ")
            machine.send("testpass123")
            screenshot(machine, directory, "persisted.ppm", 1024, 768)
            machine.send("settings", "Select: ")
            machine.send("10", "Resolution: ")
            machine.send("2", "Reverting automatically in 15 seconds unless confirmed.")
            screenshot(machine, directory, "unconfirmed.ppm", 800, 600)
            assert "Resolution reverted; nothing saved" in machine.wait("Select: ", timeout=20)
            screenshot(machine, directory, "reverted.ppm", 1024, 768)
            # Explicit rejection also rolls back; colors/shell reset must not reset either preference.
            machine.send("10", "Resolution: ")
            machine.send("4", "Reverting automatically in 15 seconds unless confirmed.")
            screenshot(machine, directory, "widescreen.ppm", 1280, 720)
            assert "Resolution reverted" in machine.send("n", "Select: ")
            menu = machine.send("7", "Select: ")
            assert "5 seconds" in menu and "1024 x 768" in menu
            machine.send("10", "Resolution: ")
            machine.send("d", "Reverting automatically in 15 seconds unless confirmed.")
            machine.send("y", "Select: ")
            screenshot(machine, directory, "default.ppm", 640, 480)
            machine.send("0")
            config = machine.send("cat /home/.tinygptrc")
            assert "display_width=0" in config and "display_height=0" in config
            machine.send("reboot", "Auto boot in 5 seconds.")
            machine.wait("Username: ")
            machine.send("tester", "Password: ")
            machine.send("testpass123")
            screenshot(machine, directory, "default-reboot.ppm", 640, 480)
            machine.process.stdin.write(b"shutdown\n")
            machine.process.stdin.flush()
            machine.process.wait(timeout=10)
            assert machine.process.returncode == 0
            print("PASS: timer validation/save/reboot/recovery window, resolution preview/confirm/persistence, timeout and explicit rollback, boot-default restore")
        finally:
            machine.close()
            if args.artifacts:
                args.artifacts.mkdir(parents=True, exist_ok=True)
                for path in directory.iterdir():
                    if path.suffix in (".ppm", ".log"):
                        shutil.copy2(path, args.artifacts / path.name)


if __name__ == "__main__":
    main()
