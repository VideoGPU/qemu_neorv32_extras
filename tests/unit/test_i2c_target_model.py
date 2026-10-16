#!/usr/bin/env python3
"""
Unit test for the neorv32.i2c-target model (i2c_target_ip on the XBUS) and
the clock-stretching i2c-master-chardev.

Boots the bare-metal probe binaries/tests/i2c_target_probe.bin as -bios and
acts as the I2C master. The probe serves four EEPROMs (0x54..0x57), an
OV5693-like 16-bit register device (0x36) and a statistics device (0x5F)
through the IP's event protocol, woken by the machine external interrupt.
Every read byte is requested from the probe while the master waits
(clock stretching); the test checks:

  1. reads, writes and combined write + repeated START + read (WR) on all
     five camera addresses, including a 256-byte EEPROM read
  2. foreign addresses are NACKed
  3. one TXREQ per byte read and a sane interrupt line (statistics device)
  4. the stretch watchdog: a probe that stops serving costs one 20 ms stretch
     and 0xFF bytes, and its late answers never leak into the next transfer
  5. the same with bus timing (bus-hz=400000)

QEMU runs with -icount so that virtual time, and with it the IP's stretch
watchdog, follows guest instructions rather than host load.

Probe source: tests/unit/src/i2c_target_probe/ (rebuild with build.sh).

    QEMU_RISCV32_BIN=/path/to/qemu-system-riscv32 \
    python3 -m tests.unit.test_i2c_target_model
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
except ImportError:  # run as a script
    from qemu_output import (
        POPEN_GROUP_KWARGS, QemuOutputReader, stop_process_group)

OVERALL_TIMEOUT_SEC = 60.0


def eeprom(n, i):
    return (i ^ (0x5A + 0x11 * n)) & 0xFF


def d(values):
    return "D " + " ".join(f"{v:02x}" for v in values)


def find_repo_root() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    if not (repo_root / "README.md").is_file():
        raise RuntimeError(f"Could not find README.md at {repo_root}")
    return repo_root


def get_qemu_bin() -> Path:
    qemu_path = os.environ.get("QEMU_RISCV32_BIN")
    if not qemu_path:
        raise RuntimeError("Environment variable QEMU_RISCV32_BIN is not set.")
    qemu_bin = Path(qemu_path).expanduser().resolve()
    if not qemu_bin.is_file():
        raise RuntimeError(f"QEMU binary not found at {qemu_bin}")
    return qemu_bin


def command(sock: socket.socket, cmd: str) -> str:
    sock.sendall((cmd + "\n").encode())
    reply = b""
    while not reply.endswith(b"\n"):
        chunk = sock.recv(65536)
        if not chunk:
            raise ConnectionError("i2c-master-chardev closed the socket")
        reply += chunk
    return reply.decode().strip()


def connect(path: str, deadline: float) -> socket.socket:
    while True:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(path)
            return sock
        except OSError:
            sock.close()
            if time.time() > deadline:
                raise
            time.sleep(0.1)


def wait_line(reader, lines, wanted, deadline):
    while time.time() < deadline:
        if any(wanted in line for line in lines):
            return
        for raw in reader.read_lines(0.2):
            line = raw.rstrip("\r\n")
            print(f"[QEMU] {line}")
            lines.append(line)
            if "PROBE: FAIL" in line:
                raise AssertionError(line)
        if reader.eof:
            break
    raise AssertionError(f"no {wanted!r} from the probe; got {lines}")


def run_session(qemu_bin: Path, probe: Path, bus_hz: int) -> None:
    with tempfile.TemporaryDirectory(prefix="i2ct-model-") as tmp:
        sock_path = os.path.join(tmp, "i2c.sock")
        dev = "i2c-master-chardev,chardev=m,bus=i2c"
        if bus_hz:
            dev += f",bus-hz={bus_hz}"
        # -icount: virtual time follows guest instructions, so the 20 ms stretch
        # watchdog and the probe's 200 ms pause do not depend on host load
        cmd = [str(qemu_bin), "-nographic", "-M", "neorv32", "-bios", str(probe),
               "-icount", "shift=3", "-monitor", "none", "-serial", "stdio",
               "-chardev", f"socket,id=m,path={sock_path},server=on,wait=off",
               "-device", dev]
        print(f"[INFO] Command: {' '.join(cmd)}")
        sys.stdout.flush()
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, **POPEN_GROUP_KWARGS)
        reader = QemuOutputReader(proc)
        lines = []
        deadline = time.time() + OVERALL_TIMEOUT_SEC
        try:
            wait_line(reader, lines, "PROBE: ready", deadline)
            n_read = 0
            with connect(sock_path, deadline) as sock:
                def check(req, want):
                    nonlocal n_read
                    reply = command(sock, req)
                    shown = reply if len(reply) < 80 else reply[:77] + "..."
                    print(f"[I2C] {req} -> {shown}")
                    if reply != want:
                        raise AssertionError(f"{req!r}: got {reply!r}, expected {want!r}")
                    if reply.startswith("D "):
                        n_read += len(reply.split()) - 1

                check("R 0x54 4", d(eeprom(0, i) for i in range(4)))
                check("R 0x54 2", d(eeprom(0, i) for i in range(4, 6)))
                check("WR 0x55 1 0x10 3", d(eeprom(1, i) for i in range(0x10, 0x13)))
                check("W 0x56 3 0x20 0xaa 0xbb", "OK")
                check("WR 0x56 1 0x20 2", "D aa bb")
                check("WR 0x36 2 0x3d 0x00 4", "D ab cd ef 00")
                check("W 0x36 4 0x12 0x34 0x55 0x66", "OK")
                check("WR 0x36 2 0x12 0x34 2", "D 55 66")
                check("WR 0x57 1 0x00 256", d(eeprom(3, i) for i in range(256)))
                check("R 0x33 1", "ERR address NACK")
                check("W 0x50 1 0x00", "ERR address NACK")
                # statistics: one TXREQ per byte read (this read's first byte included)
                stats = command(sock, "R 0x5f 6").split()[1:]
                txreq = int(stats[0], 16) | int(stats[1], 16) << 8
                print(f"[I2C] stats: txreq={txreq} irq_ok={stats[2]} wdog={stats[3]} "
                      f"skipped={stats[4]}")
                if txreq != n_read + 1 or stats[2] != "01" or stats[3] != "00":
                    raise AssertionError(f"statistics {stats}, {n_read} bytes read")

                # watchdog: the probe stops serving for 200 ms
                check("W 0x5f 1 0xdd", "OK")
                check("R 0x54 2", "D ff ff")
                # while paused every read stretches into the watchdog and returns
                # 0xff; poll the stats device (last byte 0x5f) until it is served
                deadline = time.monotonic() + 30.0
                while True:
                    stats = command(sock, "R 0x5f 6").split()[1:]
                    if len(stats) == 6 and stats[5] == "5f":
                        break
                    if time.monotonic() > deadline:
                        raise AssertionError(f"probe did not resume serving: {stats}")
                    time.sleep(0.05)
                print(f"[I2C] stats after watchdog: wdog={stats[3]} skipped={stats[4]}")
                if int(stats[3], 16) < 1 or int(stats[4], 16) < 1:
                    raise AssertionError(f"watchdog not seen by the probe: {stats}")
                # the late answer did not advance the model nor leak
                check("WR 0x54 1 0x06 2", d(eeprom(0, i) for i in (6, 7)))
                check("R 0x54 1", d([eeprom(0, 8)]))
        finally:
            stop_process_group(proc)


def run_i2c_target_model_test() -> None:
    repo_root = find_repo_root()
    qemu_bin = get_qemu_bin()
    probe = repo_root / "binaries" / "tests" / "i2c_target_probe.bin"
    if not probe.is_file():
        raise RuntimeError(f"probe binary not found at {probe}")
    for bus_hz in (0, 400000):
        print(f"[INFO] --- bus-hz={bus_hz} ---")
        run_session(qemu_bin, probe, bus_hz)
    print("[INFO] i2c target model test PASSED.")


def main() -> int:
    try:
        run_i2c_target_model_test()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
