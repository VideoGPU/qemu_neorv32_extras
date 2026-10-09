#!/usr/bin/env python3
"""
Unit test for the bootloader "i" (system info) command and the NEORV32
mxisa / mxisah CSRs.

The stock bootloader prints HWV, CLK, MISA, then XISA by reading mxisah
(0xFC1) and mxisa (0xFC0), then the SYSINFO SOC and MISC registers. A CPU
model without mxisah traps there with ERROR_EXCEPTION 0x00000002 (illegal
instruction) and never prints SOC / MISC.

Boots the bundled bootloader (or NEORV32_BOOTLOADER_BIN) as -bios, aborts the
auto-boot countdown, sends "i" and checks every line plus the MISC encoding
of the 32 KiB IMEM / DMEM the machine models.

    QEMU_RISCV32_BIN=/path/to/qemu-system-riscv32 \
    python3 -m tests.unit.test_bootloader_sysinfo
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from tests.unit.qemu_output import (
        POPEN_GROUP_KWARGS, QemuOutputReader, stop_process_group)
except ImportError:  # run as a script: python3 tests/unit/<test>.py
    from qemu_output import (
        POPEN_GROUP_KWARGS, QemuOutputReader, stop_process_group)

OVERALL_TIMEOUT_SEC = 30.0
PROMPT = "CMD:> "
HEX = r"0x[0-9A-F]{8}"
EXPECTED = (
    ("HWV", rf"^HWV:  {HEX}$"),
    ("CLK", rf"^CLK:  {HEX}$"),
    ("MISA", rf"^MISA: {HEX}$"),
    ("XISA", rf"^XISA: {HEX}_{HEX}$"),
    ("SOC", rf"^SOC:  {HEX}$"),
    ("MISC", rf"^MISC: ({HEX})$"),
)


def find_repo_root() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    if not (repo_root / "README.md").is_file():
        raise RuntimeError(f"Could not find README.md at {repo_root}")
    return repo_root


def get_qemu_bin() -> Path:
    env_name = "QEMU_RISCV32_BIN"
    qemu_path = os.environ.get(env_name)
    if not qemu_path:
        raise RuntimeError(
            f"Environment variable {env_name} is not set.\n"
            f"    export {env_name}=/path/to/qemu-system-riscv32"
        )
    qemu_bin = Path(qemu_path).expanduser().resolve()
    if not qemu_bin.is_file():
        raise RuntimeError(f"QEMU binary not found at {qemu_bin}")
    return qemu_bin


def get_bootloader(repo_root: Path) -> Path:
    override = os.environ.get("NEORV32_BOOTLOADER_BIN")
    path = Path(override).expanduser() if override else (
        repo_root / "binaries" / "bootloader" / "neorv32_raw_exe.bin")
    if not path.is_file():
        raise RuntimeError(f"bootloader not found at {path}")
    return path


def run_sysinfo_test() -> None:
    repo_root = find_repo_root()
    qemu_bin = get_qemu_bin()
    bootloader = get_bootloader(repo_root)

    cmd = [
        str(qemu_bin), "-nographic", "-M", "neorv32",
        "-bios", str(bootloader), "-monitor", "none", "-serial", "stdio",
    ]
    print(f"[INFO] Command: {' '.join(cmd)}")
    sys.stdout.flush()

    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, **POPEN_GROUP_KWARGS,
    )
    reader = QemuOutputReader(proc)
    lines = []
    state = "banner"
    deadline = time.time() + OVERALL_TIMEOUT_SEC

    def send(text: str) -> None:
        proc.stdin.write(text.encode())
        proc.stdin.flush()

    try:
        while time.time() < deadline and not reader.eof and state != "done":
            for raw in reader.read_lines(0.2):
                line = raw.rstrip("\r\n")
                print(f"[QEMU] {line}")
                lines.append(line)
                if "ERROR_EXCEPTION" in line:
                    raise AssertionError(f"bootloader trapped: {line!r}")
                if state == "banner" and "Press any key to abort." in line:
                    send(" ")
                    state = "abort"
            partial = reader.partial_line()
            if state == "abort" and partial == PROMPT:
                send("i")
                state = "info"
            elif state == "info" and partial == PROMPT and any(
                    line.startswith("MISC:") for line in lines):
                state = "done"
    finally:
        stop_process_group(proc)

    if state != "done":
        raise AssertionError(
            f"system info not complete within {OVERALL_TIMEOUT_SEC}s "
            f"(state {state}); got {lines}")

    values = {}
    for name, pattern in EXPECTED:
        matches = [m for m in (re.match(pattern, line) for line in lines) if m]
        if not matches:
            raise AssertionError(f"no well-formed {name} line in {lines}")
        values[name] = matches[-1]

    misc = int(values["MISC"].group(1), 16)
    imem_log2, dmem_log2 = misc & 0xFF, (misc >> 8) & 0xFF
    if (imem_log2, dmem_log2) != (15, 15):
        raise AssertionError(
            f"MISC 0x{misc:08X}: expected log2 IMEM/DMEM 15/15 (32 KiB), "
            f"got {imem_log2}/{dmem_log2}")
    print("[INFO] bootloader sysinfo test PASSED.")


def main() -> int:
    try:
        run_sysinfo_test()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
