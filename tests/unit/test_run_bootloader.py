#!/usr/bin/env python3
"""
Unit test for scripts/bash/run_bootloader.sh

This is intended to be runnable in CI, e.g.:

    QEMU_RISCV32_BIN=/path/to/qemu-system-riscv32 \
    python3 -m tests.unit.test_run_bootloader

Requirements:
    - QEMU built with the neorv32 machine
    - qemu_neorv32_extras repo layout as expected
"""

import os
import sys
import time
import subprocess
from pathlib import Path

try:
    from tests.unit.qemu_output import (
        POPEN_GROUP_KWARGS, QemuOutputReader, stop_process_group)
except ImportError:  # run as a script: python3 tests/unit/<test>.py
    from qemu_output import (
        POPEN_GROUP_KWARGS, QemuOutputReader, stop_process_group)

# How long we allow QEMU to run before forcing termination
OVERALL_TIMEOUT_SEC = 60.0


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


def run_bootloader_test() -> None:
    repo_root = find_repo_root()
    qemu_bin = get_qemu_bin()

    run_script = repo_root / "scripts" / "bash" / "run_bootloader.sh"
    if not run_script.is_file():
        raise RuntimeError(f"run_bootloader.sh not found at {run_script}")
    if not os.access(run_script, os.X_OK):
        raise RuntimeError(f"run_bootloader.sh is not executable: {run_script}")

    cmd = [str(run_script), "-q", str(qemu_bin)]

    print(f"[INFO] Repo root: {repo_root}")
    print(f"[INFO] QEMU bin:  {qemu_bin}")
    print(f"[INFO] Script:    {run_script}")
    print(f"[INFO] Command:   {' '.join(cmd)}")
    sys.stdout.flush()

    start_time = time.time()

    # Run QEMU via the wrapper script
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        **POPEN_GROUP_KWARGS,
    )
    reader = QemuOutputReader(proc)

    bootloader_seen = False

    try:
        while True:
            # Timeout handling
            elapsed = time.time() - start_time
            if elapsed > OVERALL_TIMEOUT_SEC:
                print(
                    f"[ERROR] Timeout: QEMU did not complete within "
                    f"{OVERALL_TIMEOUT_SEC} seconds"
                )
                stop_process_group(proc)
                raise RuntimeError(
                    "Timeout waiting for QEMU / bootloader output; last partial "
                    f"line: {reader.partial_line()!r}"
                )

            lines = reader.read_lines(0.5)
            if not lines:
                if reader.eof:
                    break
                continue
            for line in lines:
                # Echo QEMU output to our stdout (useful for CI logs)
                sys.stdout.write(line)
            sys.stdout.flush()

            if any("NEORV32 Bootloader" in line for line in lines) and not bootloader_seen:
                bootloader_seen = True
                print("[INFO] Detected NEORV32 Bootloader banner, sending Ctrl-a x...")
                sys.stdout.flush()

                # Send Ctrl-a, then 'x' to QEMU (-nographic monitor hotkey)
                if proc.stdin:
                    proc.stdin.write("\x01x")
                    proc.stdin.flush()
                # After this, QEMU should quit shortly; we'll exit loop on EOF/exit
                # Don't break immediately; allow some more lines to flush
                # but avoid blocking forever. We'll rely on timeout + EOF.

        # After stdout loop, wait for process to really exit
        try:
            rc = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print("[ERROR] QEMU did not exit after Ctrl-a x; killing it.")
            stop_process_group(proc)
            rc = proc.returncode

        if not bootloader_seen:
            raise RuntimeError(
                "Did not detect 'NEORV32 Bootloader' in QEMU output; boot may have failed."
            )

        if rc != 0:
            raise RuntimeError(f"QEMU exited with non-zero status: {rc}")

        print("[INFO] run_bootloader.sh test PASSED.")

    finally:
        # Safety: ensure neither the wrapper nor QEMU is left running
        stop_process_group(proc)


def main() -> int:
    try:
        run_bootloader_test()
    except Exception as e:
        print(f"[FAIL] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

