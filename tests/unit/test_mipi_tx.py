#!/usr/bin/env python3
"""
Unit test for the NEORV32 QEMU MIPI CSI-2 TX IP using flash boot.

Flow (based on docs/system/riscv/neorv32.rst):
1. Generate a flash image via scripts/bash/generate_flash_image.sh
2. Boot QEMU with the CSI-2 dump file enabled
3. Verify demo_mipi_tx detects the IP and completes every frame
4. Verify the captured CSI-2 stream: framing, header ECC and payload CRC

This test is intended to be runnable in CI, e.g.:

    QEMU_RISCV32_BIN=/path/to/qemu-system-riscv32 \
    NEORV32_BOOTLOADER_BIN=/path/to/neorv32_raw_exe.bin \
    python3 tests/unit/test_mipi_tx.py

NEORV32_BOOTLOADER_BIN is optional. The bundled bootloader is built from the
NEORV32 revision in binaries/neorv32_commit_id.txt; override it when the
payload comes from a different NEORV32 revision, because the bootloader and
image_gen executable headers must match (a mismatch fails with
ERROR_SIGNATURE).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from tests.unit.qemu_output import (
        POPEN_GROUP_KWARGS, QemuOutputReader, stop_process_group)
except ImportError:  # run as a script: python3 tests/unit/test_mipi_tx.py
    from qemu_output import (
        POPEN_GROUP_KWARGS, QemuOutputReader, stop_process_group)

# Includes the bootloader auto-boot countdown (8 s, CLINT in SYSINFO).
OVERALL_TIMEOUT_SEC = 180.0

FLASH_SIZE_HEX = "0x04000000"
FLASH_OFFSET_HEX = "0x00400000"
FLASH_IMAGE_NAME = "flash_demo_mipi_tx_64mb.bin"

# Must match sw/example/demo_mipi_tx/main.c
EXPECTED_FRAMES = 4
EXPECTED_PIXELS = 640
EXPECTED_LINES = 480
EXPECTED_WORD_COUNT = (EXPECTED_PIXELS * 10) // 8
EXPECTED_FRAME_END_WORD = 0x1753

DT_FRAME_START = 0x00
DT_FRAME_END = 0x01
DT_RAW10 = 0x2B

HEADER_ECC_PARITY_INDEXES = (
    (0, 1, 2, 4, 5, 7, 10, 11, 13, 16, 20, 21, 22, 23),
    (0, 1, 3, 4, 6, 8, 10, 12, 14, 17, 20, 21, 22, 23),
    (0, 2, 3, 5, 6, 9, 11, 12, 15, 18, 20, 21, 22),
    (1, 2, 3, 7, 8, 9, 13, 14, 15, 19, 20, 21, 23),
    (4, 5, 6, 7, 8, 9, 16, 17, 18, 19, 20, 22, 23),
    (10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23),
)


def find_repo_root() -> Path:
    """Return repo root as Path, based on this file location."""
    this_file = Path(__file__).resolve()
    repo_root = this_file.parents[2]  # tests/unit/ -> tests/ -> repo root
    if not (repo_root / "README.md").is_file():
        raise RuntimeError(f"Could not find README.md at {repo_root}")
    return repo_root


def get_qemu_bin() -> Path:
    """Get QEMU binary path from env var QEMU_RISCV32_BIN."""
    env_name = "QEMU_RISCV32_BIN"
    qemu_path = os.environ.get(env_name)
    if not qemu_path:
        raise RuntimeError(
            f"Environment variable {env_name} is not set.\n"
            f"Set it to your qemu-system-riscv32 binary, e.g.:\n"
            f"    export {env_name}=/path/to/qemu-system-riscv32"
        )
    qemu_bin = Path(qemu_path).expanduser().resolve()
    if not qemu_bin.is_file():
        raise RuntimeError(f"QEMU binary not found at {qemu_bin}")
    return qemu_bin


def get_demo_payload(repo_root: Path) -> Path:
    """
    Resolve demo_mipi_tx payload path.

    Priority:
    1) NEORV32_DEMO_MIPI_TX_BIN env var
    2) Bundled binaries/examples/demo_mipi_tx/neorv32_exe.bin
    3) Workspace sibling NEORV32 tree
    """
    env_name = "NEORV32_DEMO_MIPI_TX_BIN"
    payload = os.environ.get(env_name)
    if payload:
        payload_path = Path(payload).expanduser().resolve()
        if not payload_path.is_file():
            raise RuntimeError(f"{env_name} set but file not found: {payload_path}")
        return payload_path

    bundled = repo_root / "binaries" / "examples" / "demo_mipi_tx" / "neorv32_exe.bin"
    if bundled.is_file():
        return bundled

    # /.../sources/qemu_neorv32_extras -> /.../ (workspace base), then fpga_projects
    workspace_base = repo_root.parent.parent
    payload_path = (
        workspace_base
        / "fpga_projects"
        / "neorv32"
        / "sw"
        / "example"
        / "demo_mipi_tx"
        / "neorv32_exe.bin"
    ).resolve()

    if not payload_path.is_file():
        raise RuntimeError(
            "Could not find demo_mipi_tx payload binary.\n"
            f"Expected at: {bundled}\n"
            f"Or at: {payload_path}\n"
            f"Or set {env_name}=/path/to/sw/example/demo_mipi_tx/neorv32_exe.bin"
        )

    return payload_path


def get_bootloader_bin(repo_root: Path) -> Path:
    """Resolve bootloader, with optional override from env var."""
    env_name = "NEORV32_BOOTLOADER_BIN"
    bootloader = os.environ.get(env_name)
    if bootloader:
        bootloader_path = Path(bootloader).expanduser().resolve()
        if not bootloader_path.is_file():
            raise RuntimeError(f"{env_name} set but file not found: {bootloader_path}")
        return bootloader_path

    bundled = repo_root / "binaries" / "bootloader" / "neorv32_raw_exe.bin"
    if not bundled.is_file():
        raise RuntimeError(f"Bootloader not found at {bundled}")
    return bundled


def generate_flash_image(repo_root: Path, payload: Path) -> Path:
    """Generate test flash image using scripts/bash/generate_flash_image.sh."""
    script = repo_root / "scripts" / "bash" / "generate_flash_image.sh"
    if not script.is_file():
        raise RuntimeError(f"generate_flash_image.sh not found at {script}")
    if not os.access(script, os.X_OK):
        raise RuntimeError(f"generate_flash_image.sh is not executable: {script}")

    output = repo_root / "binaries" / "flash_images" / FLASH_IMAGE_NAME

    cmd = [
        str(script),
        "-p", str(payload),
        "-o", str(output),
        "-s", FLASH_SIZE_HEX,
        "-O", FLASH_OFFSET_HEX,
    ]

    print(f"[INFO] Generating flash image: {' '.join(cmd)}")
    sys.stdout.flush()
    subprocess.run(cmd, check=True)

    if not output.is_file():
        raise RuntimeError(f"Flash image was not created: {output}")

    return output


def run_demo(qemu_bin: Path, bootloader: Path, flash: Path, dumpfile: Path) -> list[str]:
    """Boot the demo and collect UART output until it reports completion."""
    cmd = [
        str(qemu_bin),
        "-nographic",
        "-machine", "neorv32",
        "-bios", str(bootloader),
        "-drive", f"file={flash},if=mtd,format=raw",
        "-global", f"driver=neorv32.mipi-tx,property=dumpfile,value={dumpfile}",
    ]

    print(f"[INFO] Running QEMU: {' '.join(cmd)}")
    sys.stdout.flush()

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        **POPEN_GROUP_KWARGS,
    )
    reader = QemuOutputReader(proc)

    collected: list[str] = []
    deadline = time.time() + OVERALL_TIMEOUT_SEC

    try:
        while time.time() < deadline and not reader.eof:
            for line in reader.read_lines(0.4):
                collected.append(line)
                sys.stdout.write(line)
                sys.stdout.flush()

                if "Done." in line or "ERROR!" in line:
                    return collected

        reason = "QEMU exited" if reader.eof else "Timeout"
        raise RuntimeError(
            f"{reason} before demo_mipi_tx finished.\nOutput so far:\n"
            + "".join(collected[-120:])
            + reader.partial_line()
        )
    finally:
        stop_process_group(proc, grace_sec=10)


def check_uart_output(lines: list[str]) -> None:
    """Verify the demo detected the IP and completed all frames."""
    text = "".join(lines)

    if "MIPI TX IP not detected" in text:
        raise AssertionError("demo_mipi_tx did not detect the MIPI TX IP")
    if "ERROR!" in text:
        raise AssertionError(f"demo_mipi_tx reported an error:\n{text}")

    for index in range(EXPECTED_FRAMES):
        marker = f"Frame {index} done"
        if marker not in text:
            raise AssertionError(f"Missing UART marker: {marker!r}")

    # STATUS[2] frame done and STATUS[3] irq pending must be set after a frame
    if "status 0x0000000c" not in text:
        raise AssertionError("Unexpected MIPI TX status reported by the demo")

    print(f"[PASS] demo_mipi_tx completed {EXPECTED_FRAMES} frame(s)")


def compute_header_ecc(data_id: int, byte1: int, byte2: int) -> int:
    """Compute the CSI-2 packet header ECC over the first 24 header bits."""
    header24 = data_id | (byte1 << 8) | (byte2 << 16)
    ecc = 0
    for bit_index, indexes in enumerate(HEADER_ECC_PARITY_INDEXES):
        parity = 0
        for idx in indexes:
            parity ^= (header24 >> idx) & 1
        ecc |= parity << bit_index
    return ecc


def crc16_ccitt_false(payload: bytes) -> int:
    """CRC16-CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection)."""
    crc = 0xFFFF
    for value in payload:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def check_dumpfile(dumpfile: Path) -> None:
    """Parse the captured CSI-2 stream and verify framing, ECC and CRC."""
    if not dumpfile.is_file():
        raise AssertionError(f"CSI-2 dump file was not created: {dumpfile}")

    data = dumpfile.read_bytes()
    offset = 0
    frames = 0
    lines_in_frame = 0

    while offset < len(data):
        if offset + 4 > len(data):
            raise AssertionError(f"Truncated packet header at offset {offset}")

        data_id, byte1, byte2, ecc = data[offset:offset + 4]
        data_type = data_id & 0x3F
        word = byte1 | (byte2 << 8)

        if ecc != compute_header_ecc(data_id, byte1, byte2):
            raise AssertionError(f"Bad header ECC at offset {offset}")

        if data_type == DT_FRAME_START:
            if lines_in_frame:
                raise AssertionError("Frame Start inside an open frame")
            if word != frames + 1:
                raise AssertionError(
                    f"Unexpected frame number {word}, expected {frames + 1}"
                )
            offset += 4
        elif data_type == DT_FRAME_END:
            if word != EXPECTED_FRAME_END_WORD:
                raise AssertionError(f"Unexpected frame end word 0x{word:04x}")
            if lines_in_frame != EXPECTED_LINES:
                raise AssertionError(
                    f"Frame {frames} has {lines_in_frame} lines, "
                    f"expected {EXPECTED_LINES}"
                )
            lines_in_frame = 0
            frames += 1
            offset += 4
        elif data_type == DT_RAW10:
            if word != EXPECTED_WORD_COUNT:
                raise AssertionError(
                    f"Unexpected word count {word}, expected {EXPECTED_WORD_COUNT}"
                )
            payload_end = offset + 4 + word
            if payload_end + 2 > len(data):
                raise AssertionError(f"Truncated long packet at offset {offset}")
            payload = data[offset + 4:payload_end]
            crc = data[payload_end] | (data[payload_end + 1] << 8)
            if crc != crc16_ccitt_false(payload):
                raise AssertionError(f"Bad payload CRC at offset {offset}")
            lines_in_frame += 1
            offset = payload_end + 2
        else:
            raise AssertionError(
                f"Unexpected data type 0x{data_type:02x} at offset {offset}"
            )

    if frames != EXPECTED_FRAMES:
        raise AssertionError(f"Captured {frames} frame(s), expected {EXPECTED_FRAMES}")

    print(
        f"[PASS] CSI-2 dump: {frames} frame(s), {EXPECTED_LINES} lines each, "
        f"WC={EXPECTED_WORD_COUNT}, ECC and CRC OK"
    )


def main() -> int:
    repo_root = find_repo_root()
    qemu_bin = get_qemu_bin()
    payload = get_demo_payload(repo_root)
    bootloader = get_bootloader_bin(repo_root)

    print(f"[INFO] Repo root:  {repo_root}")
    print(f"[INFO] QEMU:       {qemu_bin}")
    print(f"[INFO] Bootloader: {bootloader}")
    print(f"[INFO] Payload:    {payload}")

    flash = generate_flash_image(repo_root, payload)

    with tempfile.TemporaryDirectory(prefix="neorv32-mipi-tx-") as tmpdir:
        dumpfile = Path(tmpdir) / "mipi_tx_stream.bin"
        lines = run_demo(qemu_bin, bootloader, flash, dumpfile)
        check_uart_output(lines)
        check_dumpfile(dumpfile)

    print("[PASS] test_mipi_tx")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - test entry point
        print(f"[FAIL] {exc}", file=sys.stderr)
        sys.exit(1)
