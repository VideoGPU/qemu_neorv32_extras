# qemu_neorv32_extras
Companion resources for the QEMU NEORV32 machine: prebuilt images, scripts, 
and tests.

# Basic Setup

Note: work still in progress to add the Neorv32 support to QEMU main tree,
few patch iterations are already passed.
For now this repo uses a QEMU fork.

(in bash, base path)
$

(clone this repo)
git@github.com:VideoGPU/qemu_neorv32_extras.git
cd qemu_neorv32_extras

(optionaly, create a flash image with "Hello World" example)
dd if=/dev/zero of=binaries/flash_images/flash_contents.bin bs=1 count=$((0x04000000))
dd if=binaries/examples/hello_world/neorv32_exe.bin of=binaries/flash_images/flash_contents.bin bs=1 seek=$((0x00400000)) conv=notrunc


(clone QEMU)
git clone git@github.com:VideoGPU/qemu.git
cd qemu
git checkout mlevit_neorv32_riscv_support

(Configure QEMU, python option may vary, or not needed at all)

./configure \
  --python=/usr/local/bin/python3.12 \
  --target-list=riscv32-softmmu \
  --enable-fdt \
  --enable-debug \
  --disable-vnc \
  --disable-gtk

cd build

(Run the bootloader in command line. To exit press "Ctrl-a x")
