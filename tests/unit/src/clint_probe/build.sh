#!/usr/bin/env bash
# Rebuild binaries/tests/clint_probe.bin from clint_probe.S.
# CROSS defaults to the Zephyr SDK riscv64 toolchain (multilib covers rv32).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../../.." && pwd)"
CROSS="${CROSS:-$HOME/zephyr-sdk-1.0.1/gnu/riscv64-zephyr-elf/bin/riscv64-zephyr-elf-}"
out="$repo/binaries/tests"
mkdir -p "$out"
"${CROSS}gcc" -march=rv32i_zicsr -mabi=ilp32 -nostdlib -nostartfiles \
    -T "$here/clint_probe.ld" -Wl,--no-relax \
    -o "$here/clint_probe.elf" "$here/clint_probe.S"
"${CROSS}objcopy" -O binary "$here/clint_probe.elf" "$out/clint_probe.bin"
rm -f "$here/clint_probe.elf"
echo "wrote $out/clint_probe.bin"
