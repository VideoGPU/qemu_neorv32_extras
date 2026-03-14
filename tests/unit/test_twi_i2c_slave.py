#!/usr/bin/env python3
"""
Unit test for NEORV32 TWI/I2C slave path using flash boot.

Flow (based on docs/system/riscv/neorv32.rst):
1. Generate a flash image via scripts/bash/generate_flash_image.sh
2. Boot QEMU via scripts/bash/run_with_flash.sh with a TWD socket chardev
3. Act as I2C master from host via UNIX socket commands (W/R)
4. Verify demo_twd firmware echoes bytes back from slave TX FIFO

This test is intended to be runnable in CI, e.g.:

	QEMU_RISCV32_BIN=/path/to/qemu-system-riscv32 \
	python3 -m tests.unit.test_twi_i2c_slave
"""

from __future__ import annotations

import os
import select
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

OVERALL_TIMEOUT_SEC = 120.0
SOCKET_CONNECT_TIMEOUT_SEC = 25.0

EXPECTED_I2C_ADDR = 0x32
FALLBACK_I2C_ADDR = 0x52
FLASH_SIZE_HEX = "0x04000000"
FLASH_OFFSET_HEX = "0x00400000"
FLASH_IMAGE_NAME = "flash_demo_twd_64mb.bin"


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


def get_demo_twd_payload(repo_root: Path) -> Path:
	"""
	Resolve demo_twd payload path.

	Priority:
	1) NEORV32_DEMO_TWD_BIN env var
	2) Workspace sibling: ../../fpga_projects/neorv32/sw/example/demo_twd/neorv32_exe.bin
	"""
	env_name = "NEORV32_DEMO_TWD_BIN"
	payload = os.environ.get(env_name)
	if payload:
		payload_path = Path(payload).expanduser().resolve()
		if not payload_path.is_file():
			raise RuntimeError(f"{env_name} set but file not found: {payload_path}")
		return payload_path

	# /.../sources/qemu_neorv32_extras -> /.../ (workspace base), then fpga_projects
	workspace_base = repo_root.parent.parent
	payload_path = (
		workspace_base
		/ "fpga_projects"
		/ "neorv32"
		/ "sw"
		/ "example"
		/ "demo_twd"
		/ "neorv32_exe.bin"
	).resolve()

	if not payload_path.is_file():
		raise RuntimeError(
			"Could not find demo_twd payload binary.\n"
			f"Expected at: {payload_path}\n"
			f"Or set {env_name}=/path/to/sw/example/demo_twd/neorv32_exe.bin"
		)

	return payload_path


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
		"-p",
		str(payload),
		"-o",
		str(output),
		"-s",
		FLASH_SIZE_HEX,
		"-O",
		FLASH_OFFSET_HEX,
	]

	print(f"[INFO] Generating flash image: {' '.join(cmd)}")
	sys.stdout.flush()

	# Keep generator output visible in CI logs.
	subprocess.run(cmd, check=True)

	if not output.is_file():
		raise RuntimeError(f"Flash image was not created: {output}")

	return output


def read_qemu_lines_nonblocking(proc: subprocess.Popen, timeout_sec: float) -> list[str]:
	"""Read available QEMU stdout lines for up to timeout_sec."""
	end = time.time() + timeout_sec
	lines = []

	while time.time() < end:
		if proc.stdout is None:
			return lines

		# readline() blocks; gate it with select on POSIX.
		ready, _, _ = select.select([proc.stdout], [], [], 0.1)
		if not ready:
			if proc.poll() is not None:
				# Process exited; try one final read.
				tail = proc.stdout.read()
				if tail:
					for chunk_line in tail.splitlines(True):
						lines.append(chunk_line)
				return lines
			continue

		line = proc.stdout.readline()
		if line == "":
			return lines
		lines.append(line)

	return lines


def wait_for_uart_markers(
	proc: subprocess.Popen,
	overall_start: float,
	collected: list[str],
) -> None:
	"""Wait until boot markers appear on UART output."""
	markers = [
		"NEORV32 Bootloader",
		"Booting from 0x00000000",
	]
	seen = {marker: False for marker in markers}

	while True:
		if time.time() - overall_start > OVERALL_TIMEOUT_SEC:
			missing = [m for m, ok in seen.items() if not ok]
			raise RuntimeError(
				"Timeout waiting for UART markers. Missing: "
				f"{', '.join(missing)}"
			)

		if proc.poll() is not None:
			raise RuntimeError(
				f"QEMU exited early with rc={proc.returncode}\n"
				"Output so far:\n"
				+ "".join(collected[-120:])
			)

		new_lines = read_qemu_lines_nonblocking(proc, 0.4)
		for line in new_lines:
			collected.append(line)
			sys.stdout.write(line)
			sys.stdout.flush()
			for marker in markers:
				if marker in line:
					seen[marker] = True

		if all(seen.values()):
			return


def connect_twd_socket(socket_path: Path) -> socket.socket:
	"""Connect to QEMU i2c-master-chardev UNIX socket with retries."""
	deadline = time.time() + SOCKET_CONNECT_TIMEOUT_SEC
	last_error = None

	while time.time() < deadline:
		try:
			sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
			sock.settimeout(5.0)
			sock.connect(str(socket_path))
			return sock
		except OSError as exc:
			last_error = exc
			time.sleep(0.15)

	raise RuntimeError(
		f"Failed to connect to TWD socket at {socket_path}: {last_error}"
	)


def recv_line(sock: socket.socket) -> str:
	"""Receive one CR/LF-terminated line from the TWD helper socket."""
	data = bytearray()
	while True:
		chunk = sock.recv(1)
		if not chunk:
			if data:
				return data.decode("utf-8", errors="replace")
			raise ConnectionError("socket closed by peer")
		if chunk == b"\n":
			return data.decode("utf-8", errors="replace")
		if chunk != b"\r":
			data.extend(chunk)


def send_twd_cmd(sock: socket.socket, cmd: str) -> str:
	"""Send one socket command and return one-line response."""
	payload = cmd.strip() + "\n"
	sock.sendall(payload.encode("utf-8"))
	return recv_line(sock).strip()


def parse_data_reply(reply: str) -> list[int]:
	"""Parse `D xx xx ...` response into a list of byte values."""
	if reply.startswith("ERR"):
		raise RuntimeError(f"I2C read failed: {reply}")
	if not reply.startswith("D "):
		raise RuntimeError(f"Unexpected read reply: {reply}")

	parts = reply.split()
	try:
		return [int(part, 16) for part in parts[1:]]
	except ValueError as exc:
		raise RuntimeError(f"Malformed read data reply: {reply}") from exc


def contains_subsequence(haystack: list[int], needle: list[int]) -> bool:
	"""Return True if `needle` appears contiguously in `haystack`."""
	if not needle:
		return True
	if len(needle) > len(haystack):
		return False

	for i in range(0, len(haystack) - len(needle) + 1):
		if haystack[i : i + len(needle)] == needle:
			return True
	return False


def try_find_responsive_addr(
	sock: socket.socket,
	addrs: list[int],
	timeout_sec: float,
) -> int:
	"""Probe candidate I2C addresses until one stops NACKing."""
	deadline = time.time() + timeout_sec
	last_err = "no probe attempted"

	while time.time() < deadline:
		for addr in addrs:
			cmd_addr = f"0x{addr:02x}"
			reply = send_twd_cmd(sock, f"R {cmd_addr} 01")
			if not reply.startswith("ERR address NACK"):
				print(f"[INFO] Responsive I2C address: {cmd_addr} (probe reply: {reply})")
				return addr
			last_err = f"{cmd_addr}: {reply}"
		time.sleep(0.2)

	raise RuntimeError(
		"No responsive I2C slave address found within timeout. "
		f"Last probe result: {last_err}"
	)


def send_twd_cmd_retry(
	sock: socket.socket,
	cmd: str,
	retry_timeout_sec: float,
) -> str:
	"""Retry command while the slave still NACKs during early boot."""
	deadline = time.time() + retry_timeout_sec
	last_reply = ""

	while time.time() < deadline:
		reply = send_twd_cmd(sock, cmd)
		last_reply = reply
		if reply != "ERR address NACK":
			return reply
		time.sleep(0.15)

	raise RuntimeError(f"Command kept NACKing: {cmd} -> {last_reply}")


def request_qemu_exit(proc: subprocess.Popen) -> None:
	"""Ask QEMU to quit via monitor hotkey Ctrl-a x."""
	if proc.stdin and proc.poll() is None:
		proc.stdin.write("\x01x")
		proc.stdin.flush()


def run_twi_i2c_slave_test() -> None:
	repo_root = find_repo_root()
	qemu_bin = get_qemu_bin()
	payload = get_demo_twd_payload(repo_root)
	flash_img = generate_flash_image(repo_root, payload)

	run_script = repo_root / "scripts" / "bash" / "run_with_flash.sh"
	if not run_script.is_file():
		raise RuntimeError(f"run_with_flash.sh not found at {run_script}")
	if not os.access(run_script, os.X_OK):
		raise RuntimeError(f"run_with_flash.sh is not executable: {run_script}")

	with tempfile.TemporaryDirectory(prefix="neorv32_twd_") as tmpdir:
		socket_path = Path(tmpdir) / "twd-i2c.sock"

		cmd = [
			str(run_script),
			"-q",
			str(qemu_bin),
			"-f",
			str(flash_img),
			"--",
			"-chardev",
			f"socket,id=twdm,path={socket_path},server=on,wait=off",
			"-device",
			"i2c-master-chardev,chardev=twdm,bus=i2c",
		]

		print(f"[INFO] Repo root: {repo_root}")
		print(f"[INFO] QEMU bin:  {qemu_bin}")
		print(f"[INFO] Payload:   {payload}")
		print(f"[INFO] Flash:     {flash_img}")
		print(f"[INFO] Script:    {run_script}")
		print(f"[INFO] Socket:    {socket_path}")
		print(f"[INFO] Command:   {' '.join(cmd)}")
		sys.stdout.flush()

		proc = subprocess.Popen(
			cmd,
			stdin=subprocess.PIPE,
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
			bufsize=1,
		)

		collected_output: list[str] = []
		overall_start = time.time()

		try:
			wait_for_uart_markers(proc, overall_start, collected_output)

			# Give firmware a brief moment after boot handoff before host I2C traffic.
			time.sleep(0.3)

			with connect_twd_socket(socket_path) as twd_sock:
				twd_addr_u8 = try_find_responsive_addr(
					twd_sock,
					[EXPECTED_I2C_ADDR, FALLBACK_I2C_ADDR],
					timeout_sec=12.0,
				)
				twd_addr = f"0x{twd_addr_u8:02x}"

				# Write bytes to slave and verify firmware echoes them.
				expected_echo = [0x11, 0x22, 0x33]
				write_reply = send_twd_cmd_retry(
					twd_sock,
					f"W {twd_addr} 3 0x11 0x22 0x33",
					retry_timeout_sec=6.0,
				)
				print(f"[INFO] Write reply: {write_reply}")
				if write_reply != "OK":
					raise RuntimeError(f"Unexpected write reply: {write_reply}")

				time.sleep(0.2)

				# Read enough bytes to tolerate one preloaded/legacy byte in TX FIFO.
				echo_reply = send_twd_cmd_retry(
					twd_sock,
					f"R {twd_addr} 8",
					retry_timeout_sec=6.0,
				)
				echo_data = parse_data_reply(echo_reply)
				print(f"[INFO] Echo read reply: {echo_reply}")
				if not contains_subsequence(echo_data, expected_echo):
					raise RuntimeError(
						"I2C echo mismatch. "
						f"Expected subsequence {expected_echo}, got {echo_data}"
					)

			# Let UART flush the per-byte demo messages for better debug logs.
			for line in read_qemu_lines_nonblocking(proc, 1.0):
				collected_output.append(line)
				sys.stdout.write(line)
			sys.stdout.flush()

			request_qemu_exit(proc)

			try:
				rc = proc.wait(timeout=12)
			except subprocess.TimeoutExpired:
				proc.kill()
				rc = proc.wait(timeout=5)

			if rc != 0:
				raise RuntimeError(f"QEMU exited with non-zero status: {rc}")

			print("[INFO] test_twi_i2c_slave PASSED.")

		finally:
			if proc.poll() is None:
				try:
					request_qemu_exit(proc)
					proc.wait(timeout=4)
				except Exception:
					try:
						proc.terminate()
						proc.wait(timeout=4)
					except Exception:
						try:
							proc.kill()
						except Exception:
							pass


def main() -> int:
	try:
		run_twi_i2c_slave_test()
	except Exception as exc:
		print(f"[FAIL] {exc}", file=sys.stderr)
		return 1
	return 0


if __name__ == "__main__":
	sys.exit(main())
