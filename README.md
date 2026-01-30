# qemu_neorv32_extras
Companion resources for the QEMU NEORV32 machine: prebuilt images, scripts, and tests.  
Binaries are based on commit 7d0ef6b2 , Oct 14, 2025. Before release v1.12.3 on neorv32 repo.

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

## Detailed QEMU setup and step-by-step testing:


The ``neorv32`` QEMU machine models a minimal NEORV32-based SoC sufficient to  
exercise the stock NEORV32 bootloader and run example applications from an  
emulated SPI NOR flash. It exposes a UART for console I/O and an MTD-backed  
SPI flash device that can be populated with user binaries.  


###Supported devices

The ``neorv32`` machine provides the core peripherals needed by the  
bootloader and examples:  
  
* UART for console (mapped to the QEMU stdio when ``-nographic`` or  
  ``-serial stdio`` is used).  
* SPI controller connected to an emulated SPI NOR flash (exposed to the  
  guest via QEMU's ``if=mtd`` backend).  
* Basic timer/CLINT-like facilities required by the example software.  
  
(Exact register maps and optional peripherals depend on the QEMU version and  
the specific patch series you are using.)  
  
  
###QEMU build configuration:

From the command line::
```bash
  $ /path/to/qemu/configure \
  --python=/usr/local/bin/python3.12 \
  --target-list=riscv32-softmmu \
  --enable-fdt \
  --enable-debug \
  --disable-vnc \
  --disable-gtk
```
###Boot options

Typical usage is to boot the NEORV32 bootloader as the QEMU ``-bios`` image,  
and to provide a raw SPI flash image via an MTD drive. The bootloader will  
then jump to the application image placed at the configured flash offset.  

####Preparing the SPI flash with a “Hello World” example

1. Create a 64 MiB flash image (filled with zeros)::  
```bash
   $ dd if=/dev/zero of=$HOME/flash_contents.bin bs=1 count=$((0x04000000))
```

2. Place your application binary at the **4 MiB** offset inside the flash.  
   Replace ``/path/to/neorv32_exe.bin`` with the path to your compiled  
   example application (e.g., the NEORV32 ``hello_world`` example)::  
```bash
   $ dd if=/path/to/neorv32_exe.bin of=$HOME/flash_contents.bin bs=1 seek=$((0x00400000)) conv=notrunc
```

####Running the “Hello World” example

Run QEMU with the NEORV32 bootloader as ``-bios`` and attach the prepared  
flash image via the MTD interface. Replace the placeholder paths with your  
local paths::  
```bash
  $ /path/to/qemu-system-riscv32 -nographic -machine neorv32 \
      -bios /path/to/neorv32/bootloader/neorv32_raw_exe.bin \
      -drive file=$HOME/flash_contents.bin,if=mtd,format=raw
```
  
Notes:  

* ``-nographic`` routes the UART to your terminal (Ctrl-A X to quit when  
  using the QEMU monitor hotkeys; or just close the terminal).  
* The bootloader starts first and will transfer control to your application  
  located at the 4 MiB offset of the flash image.  
* If you prefer, you can use ``-serial stdio`` instead of ``-nographic``.  

####Machine-specific options

Unless otherwise noted by the patch series, there are no special board  
options beyond the standard QEMU options shown above. Commonly useful  
generic options include:  
  
* ``-s -S`` to open a GDB stub on TCP port 1234 and start paused, so you can  
  debug both QEMU and the guest.  
* ``-d guest_errors,unimp`` (or other trace flags) for additional logging.  
  
Example: debugging with GDB::  
```bash
  $ /path/to/qemu-system-riscv32 -nographic -machine neorv32 \
      -bios /path/to/neorv32/bootloader/neorv32_raw_exe.bin \
      -drive file=$HOME/flash_contents.bin,if=mtd,format=raw \
      -s -S
```

  # In another shell:
```bash
  $ riscv32-unknown-elf-gdb /path/to/neorv32/bootloader/main.elf
  (gdb) target remote :1234
```

####Known limitations


This is a functional model intended for software bring-up and testing of  
example programs. It may not model all timing details or every optional  
peripheral available in a specific NEORV32 SoC configuration.  





