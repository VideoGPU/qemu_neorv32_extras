#!/usr/bin/env bash
#
# run_with_flash.sh
#
# Run NEORV32 QEMU machine with:
#   - A bootloader (BIOS)
#   - A flash image (64MB or any size)
#
# Defaults use repo-relative paths.
#
# Usage:
#   ./run_with_flash.sh -q /path/to/qemu-system-riscv32
#   ./run_with_flash.sh -q /path/to/qemu-system-riscv32 \
#       -b binaries/bootloader/neorv32_raw_exe.bin \
#       -f binaries/flash_images/flash_hello_world_64mb.bin
#
# Extra QEMU args:
#   ./run_with_flash.sh -q qemu-system-riscv32 -- -s -S
#

set -euo pipefail

###############################################################################
# Helpers
###############################################################################

error() {
    echo "ERROR: $*" >&2
    exit 1
}

usage() {
    cat <<EOF
Usage: $(basename "$0") -q /path/to/qemu-system-riscv32 [options] [-- <extra-qemu-args>]

Options:
  -q FILE   Path to qemu-system-riscv32 executable (required)
  -b FILE   Bootloader (BIOS) binary
            Default: binaries/bootloader/neorv32_raw_exe.bin
  -f FILE   Flash image (raw MTD)
            Default: binaries/flash_images/flash_hello_world_64mb.bin
  -h        Show this help

Examples:
  # Minimal:
  $(basename "$0") -q /path/to/qemu-system-riscv32

  # Specific files:
  $(basename "$0") -q qemu-system-riscv32 -b bootloader.bin -f flash.bin

  # With GDB stub:
  $(basename "$0") -q qemu-system-riscv32 -- -s -S
EOF
    exit 0
}

###############################################################################
# Locate repo root from script location
###############################################################################

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

if [[ ! -f "$REPO_ROOT/README.md" ]]; then
    error "Could not find README.md at repo root ($REPO_ROOT). Wrong script location?"
fi

###############################################################################
# Defaults
###############################################################################

DEFAULT_BIOS="$REPO_ROOT/binaries/bootloader/neorv32_raw_exe.bin"
DEFAULT_FLASH="$REPO_ROOT/binaries/flash_images/flash_hello_world_64mb.bin"

QEMU_BIN=""
BIOS_BIN="$DEFAULT_BIOS"
FLASH_IMG="$DEFAULT_FLASH"

###############################################################################
# Parse options
###############################################################################

while getopts ":q:b:f:h" opt; do
    case "$opt" in
        q) QEMU_BIN="$OPTARG" ;;
        b) BIOS_BIN="$OPTARG" ;;
        f) FLASH_IMG="$OPTARG" ;;
        h) usage ;;
        :)
            error "Option -$OPTARG requires an argument"
            ;;
        \?)
            error "Unknown option: -$OPTARG (use -h)"
            ;;
    esac
done
shift $((OPTIND - 1))

# Remaining args → extra QEMU args
EXTRA=()
if [[ $# -gt 0 ]]; then
    if [[ "$1" == "--" ]]; then
        shift
    fi
    if [[ $# -gt 0 ]]; then
        EXTRA=("$@")
    fi
fi

###############################################################################
# Validate paths
###############################################################################

if [[ -z "$QEMU_BIN" ]]; then
    error "QEMU binary not specified. Use -q /path/to/qemu-system-riscv32"
fi

QEMU_BIN="$(realpath -m "$QEMU_BIN")"
BIOS_BIN="$(realpath -m "$BIOS_BIN")"
FLASH_IMG="$(realpath -m "$FLASH_IMG")"

[[ -f "$QEMU_BIN" ]]  || error "QEMU binary not found: $QEMU_BIN"
[[ -f "$BIOS_BIN" ]]  || error "Bootloader (BIOS) not found: $BIOS_BIN"
[[ -f "$FLASH_IMG" ]] || error "Flash image not found: $FLASH_IMG"

###############################################################################
# Run QEMU
###############################################################################

echo "==> Running NEORV32 with bootloader + flash"
echo "    Repo root:       $REPO_ROOT"
echo "    QEMU binary:     $QEMU_BIN"
echo "    BIOS (boot):     $BIOS_BIN"
echo "    Flash image:     $FLASH_IMG"
echo "    Machine:         neorv32"

if ((${#EXTRA[@]} > 0)); then
    echo "    Extra QEMU args: ${EXTRA[*]}"
else
    echo "    Extra QEMU args: (none)"
fi
echo

set -x
"$QEMU_BIN" \
    -nographic \
    -machine neorv32 \
    -bios "$BIOS_BIN" \
    -drive file="$FLASH_IMG",if=mtd,format=raw \
    "${EXTRA[@]+"${EXTRA[@]}"}"
set +x

