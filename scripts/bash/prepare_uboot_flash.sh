#!/usr/bin/env bash
#
# prepare_uboot_flash.sh
#
# Wrap a U-Boot raw binary with NEORV32 image_gen (bootloader header)
# and place it into a SPI flash image for QEMU/NEORV32 bootloader.
#
# Requirements:
#   - NEORV32 repo with image_gen utility (built), or provide path via -g
#   - dd, stat, realpath, mktemp
#
# Usage:
#   ./prepare_uboot_flash.sh -u /path/to/u-boot.bin -n /path/to/neorv32
#   ./prepare_uboot_flash.sh -u u-boot.bin -g /path/to/image_gen
#   ./prepare_uboot_flash.sh -u u-boot.bin -n /path/to/neorv32 -B
#
#  Example:
#  prepare_uboot_flash.sh -u ~/shonot/sources/u-boot-neorv32/u-boot-dtb.bin  -g /home/smishash/shonot/sources/u-boot-neorv32/neorv32_sw_only/sw/image_gen/image_gen
#   
#
# Defaults:
#   Flash size:  0x04000000 (64 MiB)
#   Offset:      0x00400000 (4 MiB)
#   Output:      binaries/flash_images/flash_uboot_64mb.bin
#
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
Usage: $(basename "$0") -u /path/to/u-boot.bin [options]

Options:
  -u FILE   U-Boot raw binary (required)
  -n DIR    Path to NEORV32 repo (used to find image_gen at sw/image_gen/image_gen)
  -g FILE   Path to image_gen executable (overrides -n / NEORV32_REPO)
  -o FILE   Output flash image path
            (default: binaries/flash_images/flash_uboot_64mb.bin)
  -s SIZE   Flash size in bytes (decimal or hex, e.g. 67108864 or 0x04000000)
            (default: 0x04000000)
  -O OFFS   Offset in bytes where wrapped image is written (decimal or hex)
            (default: 0x00400000)
  -w FILE   Output wrapped image path (default: temp file)
  -B        Build image_gen if not found/executable (requires make)
  -h        Show this help and exit

Environment:
  NEORV32_REPO  Path to NEORV32 repo (used if -n/-g not provided)

Examples:
  $(basename "$0") -u u-boot.bin -n /path/to/neorv32
  $(basename "$0") -u u-boot.bin -g /path/to/image_gen
  $(basename "$0") -u u-boot.bin -n /path/to/neorv32 -B
EOF
    exit 0
}

# Convert a decimal or 0x-prefixed hex string to a decimal integer
parse_int() {
    local val="$1"
    if [[ ! "$val" =~ ^(0x[0-9A-Fa-f]+|[0-9]+)$ ]]; then
        error "Invalid integer value: '$val' (use decimal or 0x-prefixed hex)"
    fi
    printf '%d\n' "$((val))"
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

DEFAULT_FLASH_SIZE="0x04000000"  # 64 MiB
DEFAULT_OFFSET="0x00400000"      # 4 MiB
DEFAULT_OUTPUT="$REPO_ROOT/binaries/flash_images/flash_uboot_64mb.bin"

UBOOT_BIN=""
NEORV32_REPO="${NEORV32_REPO:-}"
IMAGE_GEN=""
OUTPUT_FLASH="$DEFAULT_OUTPUT"
FLASH_SIZE_STR="$DEFAULT_FLASH_SIZE"
OFFSET_STR="$DEFAULT_OFFSET"
WRAPPED_OUT=""
BUILD_IMAGE_GEN=0

###############################################################################
# Parse options
###############################################################################

while getopts ":u:n:g:o:s:O:w:Bh" opt; do
    case "$opt" in
        u) UBOOT_BIN="$OPTARG" ;;
        n) NEORV32_REPO="$OPTARG" ;;
        g) IMAGE_GEN="$OPTARG" ;;
        o) OUTPUT_FLASH="$OPTARG" ;;
        s) FLASH_SIZE_STR="$OPTARG" ;;
        O) OFFSET_STR="$OPTARG" ;;
        w) WRAPPED_OUT="$OPTARG" ;;
        B) BUILD_IMAGE_GEN=1 ;;
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

###############################################################################
# Validate and resolve inputs
###############################################################################

if [[ -z "$UBOOT_BIN" ]]; then
    error "U-Boot binary not specified. Use -u /path/to/u-boot.bin (see -h)."
fi

UBOOT_BIN="$(realpath -m "$UBOOT_BIN")"
OUTPUT_FLASH="$(realpath -m "$OUTPUT_FLASH")"

if [[ -n "$WRAPPED_OUT" ]]; then
    WRAPPED_OUT="$(realpath -m "$WRAPPED_OUT")"
fi

if [[ ! -f "$UBOOT_BIN" ]]; then
    error "U-Boot binary not found: $UBOOT_BIN"
fi

# Tools
for tool in dd stat realpath mktemp; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        error "Required tool '$tool' not found in PATH"
    fi
done

###############################################################################
# Resolve image_gen
###############################################################################

if [[ -z "$IMAGE_GEN" ]]; then
    if [[ -n "$NEORV32_REPO" ]]; then
        NEORV32_REPO="$(realpath -m "$NEORV32_REPO")"
        IMAGE_GEN="$NEORV32_REPO/sw/image_gen/image_gen"
    fi
fi

if [[ -z "$IMAGE_GEN" && -n "${NEORV32_REPO:-}" ]]; then
    NEORV32_REPO="$(realpath -m "$NEORV32_REPO")"
    IMAGE_GEN="$NEORV32_REPO/sw/image_gen/image_gen"
fi

if [[ -z "$IMAGE_GEN" ]]; then
    error "image_gen not specified. Use -g /path/to/image_gen or -n /path/to/neorv32 (or set NEORV32_REPO)."
fi

IMAGE_GEN="$(realpath -m "$IMAGE_GEN")"

if [[ ! -x "$IMAGE_GEN" ]]; then
    if (( BUILD_IMAGE_GEN == 1 )); then
        if [[ -z "${NEORV32_REPO:-}" ]]; then
            error "Cannot build image_gen without NEORV32_REPO. Provide -n /path/to/neorv32."
        fi
        if [[ ! -d "$NEORV32_REPO/sw/image_gen" ]]; then
            error "NEORV32 image_gen directory not found: $NEORV32_REPO/sw/image_gen"
        fi
        echo "==> Building image_gen in $NEORV32_REPO/sw/image_gen"
        (cd "$NEORV32_REPO/sw/image_gen" && make)
    else
        error "image_gen not executable or not found: $IMAGE_GEN (use -B to build)"
    fi
fi

###############################################################################
# Prepare wrapped image (bootloader header)
###############################################################################

WRAP_DIR="$(dirname "$OUTPUT_FLASH")"
mkdir -p "$WRAP_DIR"

if [[ -z "$WRAPPED_OUT" ]]; then
    WRAPPED_OUT="$(mktemp -p "$WRAP_DIR" uboot_wrapped_XXXXXX.bin)"
fi

echo "==> Wrapping U-Boot image with image_gen"
echo "    U-Boot input:   $UBOOT_BIN"
echo "    image_gen:      $IMAGE_GEN"
echo "    Wrapped output: $WRAPPED_OUT"

"$IMAGE_GEN" -i "$UBOOT_BIN" -o "$WRAPPED_OUT" -t app_bin

###############################################################################
# Create flash image and place wrapped image
###############################################################################

FLASH_SIZE_BYTES="$(parse_int "$FLASH_SIZE_STR")"
OFFSET_BYTES="$(parse_int "$OFFSET_STR")"

if (( FLASH_SIZE_BYTES <= 0 )); then
    error "Flash size must be > 0 (got $FLASH_SIZE_BYTES)"
fi

if (( OFFSET_BYTES < 0 )); then
    error "Offset must be >= 0 (got $OFFSET_BYTES)"
fi

if (( OFFSET_BYTES >= FLASH_SIZE_BYTES )); then
    error "Offset ($OFFSET_BYTES) must be smaller than flash size ($FLASH_SIZE_BYTES)"
fi

WRAPPED_SIZE_BYTES="$(stat -c '%s' "$WRAPPED_OUT")"

if (( WRAPPED_SIZE_BYTES <= 0 )); then
    error "Wrapped image size is zero or negative (stat shows $WRAPPED_SIZE_BYTES bytes)"
fi

if (( OFFSET_BYTES + WRAPPED_SIZE_BYTES > FLASH_SIZE_BYTES )); then
    error "Wrapped image ($WRAPPED_SIZE_BYTES bytes) at offset $OFFSET_BYTES does not fit in flash size $FLASH_SIZE_BYTES"
fi

# Ensure output directory exists
OUTPUT_DIR="$(dirname "$OUTPUT_FLASH")"
mkdir -p "$OUTPUT_DIR"

echo "==> Generating flash image"
echo "    Repo root:       $REPO_ROOT"
echo "    Flash size:      $FLASH_SIZE_BYTES bytes"
echo "    Offset:          $OFFSET_BYTES bytes"
echo "    Output image:    $OUTPUT_FLASH"

# Create empty flash image (zeros). Prefer truncate if available.
if command -v truncate >/dev/null 2>&1; then
    echo "    Using truncate to create sparse flash file..."
    truncate -s "$FLASH_SIZE_BYTES" "$OUTPUT_FLASH"
else
    echo "    Using dd to create zero-filled flash file..."
    dd if=/dev/zero of="$OUTPUT_FLASH" bs=1 count="$FLASH_SIZE_BYTES" status=none
fi

# Write wrapped payload into flash at the given offset
echo "    Writing wrapped U-Boot into flash image..."
dd if="$WRAPPED_OUT" of="$OUTPUT_FLASH" bs=1 seek="$OFFSET_BYTES" conv=notrunc status=none

echo "==> Done."
echo "Flash image created: $OUTPUT_FLASH"
