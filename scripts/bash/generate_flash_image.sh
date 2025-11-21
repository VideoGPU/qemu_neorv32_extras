#!/usr/bin/env bash
#
# generate_flash_image.sh
#
# Create a NEORV32 SPI flash image with a payload binary placed at a given offset.
#
# Defaults:
#   - Flash size:  0x04000000 (64 MiB)
#   - Payload:     binaries/examples/hello_world/neorv32_exe.bin
#   - Offset:      0x00400000 (4 MiB)
#   - Output file: binaries/flash_images/flash_hello_world_64mb.bin
#
# Usage:
#   ./generate_flash_image.sh
#   ./generate_flash_image.sh -p path/to/payload.bin
#   ./generate_flash_image.sh -p payload.bin -o flash.bin -s 0x04000000 -O 0x00400000
#
#
# Copyright (c) 2025 Michael Levit <michael@videogpu.com>
# SPDX-License-Identifier: GPL-2.0-or-later
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
Usage: $(basename "$0") [options]

Options:
  -p FILE   Payload binary to place into flash image
            (default: binaries/examples/hello_world/neorv32_exe.bin)
  -o FILE   Output flash image path
            (default: binaries/flash_images/flash_hello_world_64mb.bin)
  -s SIZE   Flash size in bytes (decimal or hex, e.g. 67108864 or 0x04000000)
            (default: 0x04000000)
  -O OFFS   Offset in bytes where payload is written (decimal or hex)
            (default: 0x00400000)
  -h        Show this help and exit

Examples:
  $(basename "$0")
  $(basename "$0") -p binaries/tests/my_test.bin -o binaries/flash_images/test_flash.bin
  $(basename "$0") -p payload.bin -o flash.bin -s 0x04000000 -O 0x00400000
EOF
    exit 0
}

# Convert a decimal or 0x-prefixed hex string to a decimal integer
parse_int() {
    local val="$1"
    # bash arithmetic handles both decimal and 0x... hex
    # but we want to validate it's numeric-ish
    if [[ ! "$val" =~ ^(0x[0-9A-Fa-f]+|[0-9]+)$ ]]; then
        error "Invalid integer value: '$val' (use decimal or 0x-prefixed hex)"
    fi
    # shellcheck disable=SC2003
    printf '%d\n' "$((val))"
}

###############################################################################
# Locate repo root (based on script location)
###############################################################################

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

# Basic sanity check: expect README.md at repo root
if [[ ! -f "$REPO_ROOT/README.md" ]]; then
    error "Could not find README.md at repo root ($REPO_ROOT). Are we in qemu_neorv32_extras?"
fi

###############################################################################
# Defaults
###############################################################################

DEFAULT_PAYLOAD="$REPO_ROOT/binaries/examples/hello_world/neorv32_exe.bin"
DEFAULT_OUTPUT="$REPO_ROOT/binaries/flash_images/flash_hello_world_64mb.bin"
DEFAULT_FLASH_SIZE="0x04000000"  # 64 MiB
DEFAULT_OFFSET="0x00400000"      # 4 MiB

PAYLOAD="$DEFAULT_PAYLOAD"
OUTPUT="$DEFAULT_OUTPUT"
FLASH_SIZE_STR="$DEFAULT_FLASH_SIZE"
OFFSET_STR="$DEFAULT_OFFSET"

###############################################################################
# Parse options
###############################################################################

while getopts ":p:o:s:O:h" opt; do
    case "$opt" in
        p) PAYLOAD="$OPTARG" ;;
        o) OUTPUT="$OPTARG" ;;
        s) FLASH_SIZE_STR="$OPTARG" ;;
        O) OFFSET_STR="$OPTARG" ;;
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

###############################################################################
# Resolve paths and validate inputs
###############################################################################

# Make PAYLOAD and OUTPUT absolute to be safe
PAYLOAD="$(realpath -m "$PAYLOAD")"
OUTPUT="$(realpath -m "$OUTPUT")"

FLASH_SIZE_BYTES="$(parse_int "$FLASH_SIZE_STR")"
OFFSET_BYTES="$(parse_int "$OFFSET_STR")"

# Basic numeric sanity
if (( FLASH_SIZE_BYTES <= 0 )); then
    error "Flash size must be > 0 (got $FLASH_SIZE_BYTES)"
fi

if (( OFFSET_BYTES < 0 )); then
    error "Offset must be >= 0 (got $OFFSET_BYTES)"
fi

if (( OFFSET_BYTES >= FLASH_SIZE_BYTES )); then
    error "Offset ($OFFSET_BYTES) must be smaller than flash size ($FLASH_SIZE_BYTES)"
fi

# Check payload exists
if [[ ! -f "$PAYLOAD" ]]; then
    error "Payload binary not found: $PAYLOAD"
fi

# Tools
for tool in dd stat; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        error "Required tool '$tool' not found in PATH"
    fi
done

# Get payload size
PAYLOAD_SIZE_BYTES="$(stat -c '%s' "$PAYLOAD")"

if (( PAYLOAD_SIZE_BYTES <= 0 )); then
    error "Payload size is zero or negative (stat shows $PAYLOAD_SIZE_BYTES bytes)"
fi

if (( OFFSET_BYTES + PAYLOAD_SIZE_BYTES > FLASH_SIZE_BYTES )); then
    error "Payload ($PAYLOAD_SIZE_BYTES bytes) at offset $OFFSET_BYTES does not fit in flash size $FLASH_SIZE_BYTES"
fi

# Ensure output directory exists
OUTPUT_DIR="$(dirname "$OUTPUT")"
mkdir -p "$OUTPUT_DIR"

###############################################################################
# Create flash image
###############################################################################

echo "==> Generating flash image"
echo "    Repo root:       $REPO_ROOT"
echo "    Payload:         $PAYLOAD"
echo "    Payload size:    $PAYLOAD_SIZE_BYTES bytes"
echo "    Flash size:      $FLASH_SIZE_BYTES bytes"
echo "    Offset:          $OFFSET_BYTES bytes"
echo "    Output image:    $OUTPUT"

# Create empty flash image (zeros). Prefer truncate if available.
if command -v truncate >/dev/null 2>&1; then
    echo "    Using truncate to create sparse flash file..."
    truncate -s "$FLASH_SIZE_BYTES" "$OUTPUT"
else
    echo "    Using dd to create zero-filled flash file..."
    dd if=/dev/zero of="$OUTPUT" bs=1 count="$FLASH_SIZE_BYTES" status=none
fi

# Write payload into flash at the given offset
echo "    Writing payload into flash image..."
dd if="$PAYLOAD" of="$OUTPUT" bs=1 seek="$OFFSET_BYTES" conv=notrunc status=none

echo "==> Done."
echo "Flash image created: $OUTPUT"

cat <<EOF

You can use this image with QEMU, for example (To exit QEMU press Ctrl-a x) :

  qemu-system-riscv32 \\
    -nographic \\
    -machine neorv32 \\
    -bios "$REPO_ROOT/binaries/bootloader/neorv32_raw_exe.bin" \\
    -drive file="$OUTPUT",if=mtd,format=raw

EOF

