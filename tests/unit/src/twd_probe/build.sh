#!/usr/bin/env bash
# Rebuild binaries/tests/twd_probe.bin from twd_probe.c + start.S.
# CROSS defaults to the Zephyr SDK riscv64 toolchain (multilib covers rv32).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../../../.." && pwd)"
CROSS="${CROSS:-$HOME/zephyr-sdk-1.0.1/gnu/riscv64-zephyr-elf/bin/riscv64-zephyr-elf-}"
out="$repo/binaries/tests"
mkdir -p "$out"
"${CROSS}gcc" -march=rv32i_zicsr -mabi=ilp32 -Os -ffreestanding -nostdlib \
    -nostartfiles -fno-pic -T "$here/twd_probe.ld" -Wl,--no-relax \
    -o "$here/twd_probe.elf" "$here/start.S" "$here/twd_probe.c"
"${CROSS}objcopy" -O binary "$here/twd_probe.elf" "$out/twd_probe.bin"
rm -f "$here/twd_probe.elf"
echo "wrote $out/twd_probe.bin"
