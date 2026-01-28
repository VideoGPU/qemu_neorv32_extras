# qemu_neorv32_extras
Companion resources for the QEMU NEORV32 machine: prebuilt images, scripts, and tests.

## Basic setup

### Get this repo

Assuming working dir is $HOME

```bash
cd $HOME
git clone git@github.com:VideoGPU/qemu_neorv32_extras.git
cd qemu_neorv32_extras
```
Optionaly, create a flash image with "Hello World" example)
```bash
dd if=/dev/zero of=binaries/flash_images/flash_contents.bin bs=1 count=$((0x04000000))
dd if=binaries/examples/hello_world/neorv32_exe.bin of=binaries/flash_images/flash_contents.bin bs=1 seek=$((0x00400000)) conv=notrunc
```

### Building QEMU with Neorv32 support

clone QEMU
```bash
cd $HOME
git clone git@github.com:VideoGPU/qemu.git
cd qemu
```

Configure and build the QEMU, python option may vary, or not needed at all

```bash
./configure \
  --python=/usr/local/bin/python3.12 \
  --target-list=riscv32-softmmu \
  --enable-fdt \
  --enable-debug \
  --disable-vnc \
  --disable-gtk

make -j
ls -l buld/qemu-system-riscv32
```

### Running unit tests
Set the path to qemu-system-riscv32
```bash
export QEMU_RISCV32_BIN=$HOME/qemu/build/qemu-system-riscv32
```
Run unit tests
```bash
cd $HOME/qemu_neorv32_extras
python3 tests/unit/test_run_bootloader.py
python3 tests/unit/test_run_with_flash.py
```

That's all - you have successfully run the Neorv32 specific code on QEMU emulator.
















