#!/usr/bin/env bash
# Rebuild binaries/tests/i2c_target_probe.bin from i2c_target_probe.c + start.S.
# CROSS defaults to the Zephyr SDK riscv64 toolchain (multilib covers rv32).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../../.." && pwd)"
CROSS="${CROSS:-$HOME/zephyr-sdk-1.0.1/gnu/riscv64-zephyr-elf/bin/riscv64-zephyr-elf-}"
out="$repo/binaries/tests"
mkdir -p "$out"
"${CROSS}gcc" -march=rv32i_zicsr -mabi=ilp32 -Os -ffreestanding -nostdlib \
    -nostartfiles -fno-pic -T "$here/i2c_target_probe.ld" -Wl,--no-relax \
    -o "$here/i2c_target_probe.elf" "$here/start.S" "$here/i2c_target_probe.c"
"${CROSS}objcopy" -O binary "$here/i2c_target_probe.elf" "$out/i2c_target_probe.bin"
rm -f "$here/i2c_target_probe.elf"
echo "wrote $out/i2c_target_probe.bin"
