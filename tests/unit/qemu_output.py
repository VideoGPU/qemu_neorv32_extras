"""
Shared helpers for reading QEMU console output in the unit tests.

Why this exists: file.readline() on a pipe blocks until a newline arrives. The
NEORV32 bootloader prompt ("CMD:> ") and other partial lines never end with a
newline, so a readline()-based loop stalls forever and its timeout check never
runs again. QemuOutputReader uses select() + os.read() instead and keeps
partial lines buffered, so callers always get control back on time.

The tests start QEMU either directly or through scripts/bash/*.sh, which do
not exec QEMU. Terminating only the wrapper would leave QEMU running, so
processes are started in their own session and stopped as a process group.

Both import styles are supported by the callers:
    python3 -m tests.unit.test_xxx   and   python3 tests/unit/test_xxx.py
"""

from __future__ import annotations

import os
import select
import signal
import subprocess
import time

# Popen keyword arguments that put the child (and anything it spawns) into a
# new process group, so stop_process_group() can reach QEMU behind a wrapper.
POPEN_GROUP_KWARGS = {"start_new_session": True}


class QemuOutputReader:
    """Non-blocking, line-oriented reader for a subprocess stdout pipe."""

    def __init__(self, proc: subprocess.Popen) -> None:
        if proc.stdout is None:
            raise ValueError("process was not started with stdout=PIPE")
        self._fd = proc.stdout.fileno()
        self._buf = b""
        self.eof = False

    def _pop_lines(self) -> list[str]:
        if b"\n" not in self._buf:
            return []
        head, _, self._buf = self._buf.rpartition(b"\n")
        text = head.decode("utf-8", errors="replace")
        return [line + "\n" for line in text.split("\n")]

    def read_lines(self, timeout_sec: float) -> list[str]:
        """
        Return the complete lines that arrive within timeout_sec.

        Returns as soon as at least one complete line is available, and an
        empty list if none arrived in time. At EOF the remaining partial line
        (if any) is returned as the last line and .eof is set.
        """
        deadline = time.monotonic() + timeout_sec
        while True:
            lines = self._pop_lines()
            if lines:
                return lines
            if self.eof:
                return []
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return []
            ready, _, _ = select.select([self._fd], [], [], min(remaining, 0.1))
            if not ready:
                continue
            chunk = os.read(self._fd, 4096)
            if not chunk:
                self.eof = True
                tail = self._buf.decode("utf-8", errors="replace")
                self._buf = b""
                return [tail] if tail else []
            self._buf += chunk

    def partial_line(self) -> str:
        """Text received after the last newline (e.g. a "CMD:> " prompt)."""
        return self._buf.decode("utf-8", errors="replace")


def stop_process_group(proc: subprocess.Popen, grace_sec: float = 5.0) -> None:
    """SIGTERM, then SIGKILL, the process group started for proc."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            proc.wait(timeout=grace_sec)
            # The wrapper may be gone while QEMU is still alive in the group.
            os.killpg(proc.pid, 0)
        except subprocess.TimeoutExpired:
            continue
        except ProcessLookupError:
            break
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=grace_sec)
