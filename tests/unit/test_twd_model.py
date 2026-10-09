#!/usr/bin/env python3
"""
Unit test for the NEORV32 TWD model against rtl/core/neorv32_twd.vhd.

Boots the bare-metal probe binaries/tests/twd_probe.bin directly as -bios
(no bootloader, no flash) with i2c-master-chardev on the TWD bus, and acts as
the I2C master step by step. The probe checks, on the device side:

    1. CTRL layout: FIFO size fields at bits 17 / 21, status bits 25..31
    2. interrupt sources TX_EMPTY and TX_NFULL on FIFO state (mip FIRQ0)
    3. COM_BEG / COM_END set by an addressed transfer, write-1-to-clear,
       kept when written as 0, raising the IRQ while set
    4. reads pop the TX FIFO head only when the master ACKs it, so the
       NACKed last byte is read again; an empty FIFO sends 0xFF
    5. a foreign address is NACKed and leaves no flags or data
    6. disabling the TWD clears the flags

Probe source: tests/unit/src/twd_probe/ (rebuild with build.sh).

    QEMU_RISCV32_BIN=/path/to/qemu-system-riscv32 \
    python3 -m tests.unit.test_twd_model
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from tests.unit.qemu_output import (
        POPEN_GROUP_KWARGS, QemuOutputReader, stop_process_group)
except ImportError:  # run as a script: python3 tests/unit/test_twd_model.py
    from qemu_output import (
        POPEN_GROUP_KWARGS, QemuOutputReader, stop_process_group)

OVERALL_TIMEOUT_SEC = 30.0
DEV = "0x32"
OTHER = "0x33"

# (probe step, host commands with expected replies)
STEPS = (
    ("write", ((f"W {DEV} 2 0x11 0x22", "OK"),)),
    ("read1", ((f"R {DEV} 2", "D a0 a1"),)),
    ("read2", ((f"R {DEV} 2", "D a1 a2"),)),
    ("read3", ((f"R {DEV} 3", "D a2 a3 ff"),)),
    ("nack", ((f"R {OTHER} 1", "ERR address NACK"),
              (f"W {OTHER} 1 0x77", "ERR address NACK"),
              (f"W {DEV} 1 0x5A", "OK"))),
    ("disable", ((f"W {DEV} 1 0x01", "OK"),)),
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


class Console:
    def __init__(self, proc: subprocess.Popen) -> None:
        self.reader = QemuOutputReader(proc)
        self.lines = []

    def expect(self, wanted: str, deadline: float) -> None:
        while time.time() < deadline:
            if wanted in self.lines:
                return
            for raw in self.reader.read_lines(0.2):
                line = raw.rstrip("\r\n")
                print(f"[QEMU] {line}")
                self.lines.append(line)
                if line.startswith("PROBE: FAIL"):
                    raise AssertionError(line)
            if self.reader.eof:
                break
        raise AssertionError(f"no {wanted!r} from the probe; got {self.lines}")


def connect(path: str, deadline: float) -> socket.socket:
    while True:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(path)
            return sock
        except OSError:
            sock.close()
            if time.time() > deadline:
                raise
            time.sleep(0.1)


def command(sock: socket.socket, cmd: str) -> str:
    sock.sendall((cmd + "\n").encode())
    reply = b""
    while not reply.endswith(b"\n"):
        chunk = sock.recv(256)
        if not chunk:
            raise ConnectionError("i2c-master-chardev closed the socket")
        reply += chunk
    return reply.decode().strip()


def run_twd_model_test() -> None:
    repo_root = find_repo_root()
    qemu_bin = get_qemu_bin()
    probe = repo_root / "binaries" / "tests" / "twd_probe.bin"
    if not probe.is_file():
        raise RuntimeError(f"probe binary not found at {probe}")

    with tempfile.TemporaryDirectory(prefix="twd-model-") as tmp:
        sock_path = os.path.join(tmp, "twd.sock")
        cmd = [
            str(qemu_bin), "-nographic", "-M", "neorv32",
            "-bios", str(probe), "-monitor", "none", "-serial", "stdio",
            "-chardev", f"socket,id=twdm,path={sock_path},server=on,wait=off",
            "-device", "i2c-master-chardev,chardev=twdm,bus=i2c",
        ]
        print(f"[INFO] Command: {' '.join(cmd)}")
        sys.stdout.flush()
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, **POPEN_GROUP_KWARGS,
        )
        deadline = time.time() + OVERALL_TIMEOUT_SEC
        console = Console(proc)
        try:
            console.expect("PROBE: layout OK", deadline)
            console.expect("PROBE: irq OK", deadline)
            sock = connect(sock_path, deadline)
            with sock:
                for step, transfers in STEPS:
                    console.expect(f"PROBE: ready {step}", deadline)
                    for request, expected in transfers:
                        reply = command(sock, request)
                        print(f"[I2C] {request} -> {reply}")
                        if reply != expected:
                            raise AssertionError(
                                f"{step}: {request!r} replied {reply!r}, expected {expected!r}")
                    console.expect(f"PROBE: {step} OK", deadline)
            console.expect("PROBE: PASS", deadline)
        finally:
            stop_process_group(proc)
    print("[INFO] TWD model test PASSED.")


def main() -> int:
    try:
        run_twd_model_test()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
