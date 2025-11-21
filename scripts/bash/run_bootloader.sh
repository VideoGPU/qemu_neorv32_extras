#!/usr/bin/env bash
#
# run_bootloader.sh
#
# Run NEORV32 bootloader under QEMU.
#
# Defaults:
#   - BIOS (bootloader): binaries/bootloader/neorv32_raw_exe.bin
#   - Machine:           neorv32
#   - QEMU options:      -nographic
#
# Usage:
#   ./run_bootloader.sh -q /path/to/qemu-system-riscv32
#   ./run_bootloader.sh -q /path/to/qemu-system-riscv32 -- -s -S
#
# Notes:
#   - Arguments after "--" are passed directly to QEMU.
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
Usage: $(basename "$0") -q /path/to/qemu-system-riscv32 [-- <extra-qemu-args>]

Options:
  -q FILE   Path to qemu-system-riscv32 executable (required)
  -b FILE   Path to NEORV32 bootloader (BIOS) binary
            (default: binaries/bootloader/neorv32_raw_exe.bin, relative to repo root)
  -h        Show this help and exit

Examples:
  # Minimal:
  $(basename "$0") -q /home/smishash/shonot/sources/qemu/build/qemu-system-riscv32

  # With extra QEMU options (e.g. GDB stub):
  $(basename "$0") -q /home/smishash/shonot/sources/qemu/build/qemu-system-riscv32 -- -s -S
EOF
    exit 0
}

###############################################################################
# Locate repo root (based on script location)
###############################################################################

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

if [[ ! -f "$REPO_ROOT/README.md" ]]; then
    error "Could not find README.md at repo root ($REPO_ROOT). Are we in qemu_neorv32_extras?"
fi

###############################################################################
# Defaults
###############################################################################

QEMU_BIN=""
DEFAULT_BIOS="$REPO_ROOT/binaries/bootloader/neorv32_raw_exe.bin"
BIOS_BIN="$DEFAULT_BIOS"

###############################################################################
# Parse options (before optional -- for extra QEMU args)
###############################################################################

# We need to stop at -- if present, so we parse with getopts first.
while getopts ":q:b:h" opt; do
    case "$opt" in
        q) QEMU_BIN="$OPTARG" ;;
        b) BIOS_BIN="$OPTARG" ;;
        h) usage ;;
        :)
            error "Option -$OPTARG requires an argument"
            ;;
        \?)
            error "Unknown option: -$OPTARG (use -h for help)"
            ;;
    esac
done
shift $((OPTIND - 1))

# Remaining arguments (if any) go directly to QEMU
EXTRA_QEMU_ARGS=()
if [[ "$#" -gt 0 ]]; then
    # Support optional leading "--" for clarity
    if [[ "$1" == "--" ]]; then
        shift
    fi
    if [[ "$#" -gt 0 ]]; then
        EXTRA_QEMU_ARGS=("$@")
    fi
fi

###############################################################################
# Validate inputs
###############################################################################

if [[ -z "$QEMU_BIN" ]]; then
    error "QEMU executable not specified. Use -q /path/to/qemu-system-riscv32 (see -h)."
fi

# Make QEMU_BIN and BIOS_BIN absolute
QEMU_BIN="$(realpath -m "$QEMU_BIN")"
BIOS_BIN="$(realpath -m "$BIOS_BIN")"

if [[ ! -f "$QEMU_BIN" ]]; then
    error "QEMU executable not found: $QEMU_BIN"
fi

if [[ ! -x "$QEMU_BIN" ]]; then
    echo "INFO: QEMU executable is not marked executable, attempting to run anyway: $QEMU_BIN" >&2
fi

if [[ ! -f "$BIOS_BIN" ]]; then
    error "Bootloader (BIOS) binary not found: $BIOS_BIN"
fi

###############################################################################
# Run QEMU
###############################################################################

echo "==> Running NEORV32 bootloader under QEMU"
echo "    Repo root:     $REPO_ROOT"
echo "    QEMU binary:   $QEMU_BIN"
echo "    BIOS (boot):   $BIOS_BIN"
echo "    Machine:       neorv32"
echo "    QEMU base args: -nographic -machine neorv32 -bios <bios>"
if ((${#EXTRA_QEMU_ARGS[@]} > 0)); then
    echo "    Extra QEMU args: ${EXTRA_QEMU_ARGS[*]}"
else
    echo "    Extra QEMU args: (none)"
fi
echo

set -x
"$QEMU_BIN" \
    -nographic \
    -machine neorv32 \
    -bios "$BIOS_BIN" \
    "${EXTRA_QEMU_ARGS[@]+"${EXTRA_QEMU_ARGS[@]}"}"
set +x

