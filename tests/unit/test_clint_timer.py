#!/usr/bin/env python3
"""
Unit test for the NEORV32 CLINT machine timer and privileged spec 1.12 CSRs.

Boots the bare-metal probe binaries/tests/clint_probe.bin directly as -bios
(reset vector 0xFFE00000, no bootloader, no flash) and checks, on UART0:

    1. csrw mcountinhibit does not trap   (CPU declares priv spec >= 1.11)
    2. CLINT MTIME at 0xFFF4BFF8 is mapped and advancing
    3. MTIMECMP at 0xFFF44000 raises MTIP, mcause 0x80000007

Probe source: tests/unit/src/clint_probe/ (rebuild with build.sh).

    QEMU_RISCV32_BIN=/path/to/qemu-system-riscv32 \
    python3 -m tests.unit.test_clint_timer
"""

import os
import subprocess
import sys
import time
from pathlib import Path

OVERALL_TIMEOUT_SEC = 20.0

PASS_MARKER = "PROBE: PASS"
END_MARKER = "PROBE: end"
EXPECTED_LINES = (
    "PROBE: start",
    "PROBE: mcountinhibit OK",
    "PROBE: mtime advancing OK",
    "PROBE: mtip OK",
    PASS_MARKER,
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


def run_clint_timer_test() -> None:
    repo_root = find_repo_root()
    qemu_bin = get_qemu_bin()
    probe = repo_root / "binaries" / "tests" / "clint_probe.bin"
    if not probe.is_file():
        raise RuntimeError(f"probe binary not found at {probe}")

    cmd = [
        str(qemu_bin), "-nographic", "-M", "neorv32",
        "-bios", str(probe), "-monitor", "none", "-serial", "stdio",
    ]
    print(f"[INFO] Command: {' '.join(cmd)}")
    sys.stdout.flush()

    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    lines = []
    deadline = time.time() + OVERALL_TIMEOUT_SEC
    try:
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            line = line.rstrip("\r\n")
            print(f"[QEMU] {line}")
            lines.append(line)
            if line == END_MARKER:
                break
    finally:
        proc.kill()
        proc.wait()

    if END_MARKER not in lines:
        raise AssertionError(
            f"probe did not finish within {OVERALL_TIMEOUT_SEC}s; got {lines}"
        )
    missing = [m for m in EXPECTED_LINES if m not in lines]
    if missing:
        raise AssertionError(f"missing probe lines {missing}; got {lines}")
    print("[INFO] clint timer test PASSED.")


def main() -> int:
    try:
        run_clint_timer_test()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
