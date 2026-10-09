# qemu_neorv32_extras
Companion resources for the QEMU NEORV32 machine: prebuilt images, scripts, and tests.  
Binaries are based on NEORV32 commit 994701a0 (Sep 10, 2026, `v1.13.5-75-g994701a04`), recorded in  
`binaries/neorv32_commit_id.txt`. The bundled bootloader and payloads use the `NEO!` executable header.

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
ls -l build/qemu-system-riscv32
```

`--enable-debug` is optional; release (optimised) builds work as well.

### Running unit tests
Set the path to qemu-system-riscv32
```bash
export QEMU_RISCV32_BIN=$HOME/qemu/build/qemu-system-riscv32
```

Build the `demo_twd` payload (required by the I2C slave unit test):
```bash
cd $HOME/neorv32/sw/example/demo_twd
PATH=/opt/riscv32-unknown-elf.gcc-12.1.0/bin:$PATH \
  RISCV_PREFIX=riscv32-unknown-elf- \
  make clean_all all
```

Optionally force a custom payload path:
```bash
export NEORV32_DEMO_TWD_BIN=$HOME/neorv32/sw/example/demo_twd/neorv32_exe.bin
```

When validating against a rebased or locally modified NEORV32 tree, rebuild the
bootloader from that same tree and pass it to the TWD test. This avoids using
the bundled bootloader image from this repository.

```bash
cd $HOME/neorv32/sw/bootloader
PATH=/opt/riscv32-unknown-elf.gcc-12.1.0/bin:$PATH \
  RISCV_PREFIX=riscv32-unknown-elf- \
  make clean_all all \
  MARCH=rv32imc_zicsr_zifencei \
  MABI=ilp32 \
  USER_FLAGS="-Wl,--defsym,__neorv32_ram_size=256 -Wl,--defsym,__neorv32_ram_base=0x80000000 -Wl,--defsym,__neorv32_rom_size=16k -Wl,--defsym,__neorv32_rom_base=0xFFE00000 -DMAKE_BOOTLOADER -flto"

export NEORV32_BOOTLOADER_BIN=$HOME/neorv32/sw/bootloader/neorv32_raw_exe.bin
```

The bootloader and the payload must come from the same NEORV32 revision: the
executable header written by `image_gen` changed over time (legacy
`0xB007C0DE` vs. `NEO!`), and a mismatch fails with `ERROR_SIGNATURE`. The
bundled bootloader matches the bundled payloads and a `demo_twd` built from
the NEORV32 revision in `binaries/neorv32_commit_id.txt`, so
`NEORV32_BOOTLOADER_BIN` is only needed for payloads from another revision.

Refreshing the bundled binaries for a new NEORV32 revision: build the
bootloader with the command above, build `hello_world` with
`make clean_all exe RISCV_PREFIX=riscv32-unknown-elf- MARCH=rv32imc_zicsr_zifencei MABI=ilp32`
in `sw/example/hello_world`, copy `sw/bootloader/neorv32_raw_exe.bin` to
`binaries/bootloader/` and `sw/example/hello_world/neorv32_exe.bin` to
`binaries/examples/hello_world/`, and update `binaries/neorv32_commit_id.txt`.
The bootloader binary is reproducible except for its embedded build date.

Run unit tests
```bash
cd $HOME/qemu_neorv32_extras
python3 tests/unit/test_clint_timer.py
python3 tests/unit/test_run_bootloader.py
python3 tests/unit/test_run_with_flash.py
python3 tests/unit/test_run_uboot.py
python3 tests/unit/test_twi_i2c_slave.py
python3 tests/unit/test_mipi_tx.py
```

All tests read QEMU output through `tests/unit/qemu_output.py`, which never
blocks on a partial line (such as the bootloader prompt `CMD:> `), so every
test fails at its own timeout instead of hanging, and stops QEMU together with
any `scripts/bash/*.sh` wrapper (U-Boot test excepted).

Flash-boot tests take 8 s longer than the payload itself: the machine
reports a CLINT in SYSINFO, so the stock bootloader runs its auto-boot
countdown before loading from flash. All timeouts include that margin.

`test_clint_timer.py` boots `binaries/tests/clint_probe.bin` directly as
`-bios` (no bootloader, no flash) and checks, on UART0, that:

* `csrw mcountinhibit` does not trap (CPU implements privileged spec 1.12),
* the CLINT MTIME at `0xFFF4BFF8` is mapped and advancing,
* MTIMECMP at `0xFFF44000` raises the machine timer interrupt
  (`mcause 0x80000007`).

On failure it prints the trap `mcause` of each failing check. The probe
source is in `tests/unit/src/clint_probe/`; rebuild the binary with:

```bash
tests/unit/src/clint_probe/build.sh   # CROSS=<prefix> to override the toolchain
```

`test_twi_i2c_slave.py` uses:

* `scripts/bash/generate_flash_image.sh`
* `scripts/bash/run_with_flash.sh`
* payload `sw/example/demo_twd/neorv32_exe.bin`
* optional bootloader override `NEORV32_BOOTLOADER_BIN`
* flash output in `binaries/flash_images/flash_demo_twd_64mb.bin`

`test_mipi_tx.py` uses:

* `scripts/bash/generate_flash_image.sh`
* payload `binaries/examples/demo_mipi_tx/neorv32_exe.bin`, overridable with
  `NEORV32_DEMO_MIPI_TX_BIN`
* optional bootloader override `NEORV32_BOOTLOADER_BIN`
* flash output in `binaries/flash_images/flash_demo_mipi_tx_64mb.bin`

It boots `demo_mipi_tx`, checks that the IP is detected and that all four
frames complete, and then validates the captured CSI-2 stream (framing,
header ECC and payload CRC).

Validated on 2026-09-10 against QEMU `6c5974a5db` and NEORV32
`ae4dc23de`: the test found I2C address `0x32`, wrote `11 22 33`, read the
same byte sequence back, and passed.

That's all - you have successfully run the Neorv32 specific code on QEMU emulator.

## Detailed QEMU setup and step-by-step testing:


The ``neorv32`` QEMU machine models a minimal NEORV32-based SoC sufficient to  
exercise the stock NEORV32 bootloader and run example applications from an  
emulated SPI NOR flash. It exposes a UART for console I/O and an MTD-backed  
SPI flash device that can be populated with user binaries.  


### Supported devices

The ``neorv32`` machine provides the core peripherals needed by the  
bootloader and examples:  
  
* UART for console (mapped to the QEMU stdio when ``-nographic`` or  
  ``-serial stdio`` is used).  
* SPI controller connected to an emulated SPI NOR flash (exposed to the  
  guest via QEMU's ``if=mtd`` backend).  
* TWD (two-wire device) I2C slave on an internal I2C bus.  
* MIPI CSI-2 TX AXI4-Lite IP on the external bus (XBUS), at ``0x44A00000``.  
* CLINT at ``0xFFF40000`` (SiFive-compatible layout: MSWI ``+0x0000``,  
  MTIMECMP ``+0x4000``, MTIME ``+0xBFF8``). MTIME counts at the SYSINFO core  
  clock (100 MHz), drives the ``time``/``timeh`` CSRs and raises the machine  
  timer interrupt (``mip.MTIP``). SYSINFO reports it as ``IO_CLINT``.  
* CPU implementing the RISC-V privileged specification 1.12  
  (``mcountinhibit``, ``menvcfg``, Zicntr), matching the RTL.  
  
(Exact register maps and optional peripherals depend on the QEMU version and  
the specific patch series you are using.)  
  
  
### QEMU build configuration:

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
### Boot options

Typical usage is to boot the NEORV32 bootloader as the QEMU ``-bios`` image,  
and to provide a raw SPI flash image via an MTD drive. The bootloader will  
then jump to the application image placed at the configured flash offset.  

Because SYSINFO reports the CLINT, the bootloader first prints  
``Auto-boot in 8s. Press any key to abort.`` and waits (``AUTO_BOOT_TIMEOUT``,  
8 s by default). Any key drops to the  
bootloader prompt; otherwise it loads from SPI flash when the countdown ends.  

#### Preparing the SPI flash with a “Hello World” example

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

#### Running the “Hello World” example

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

#### Running the MIPI CSI-2 TX demo

The ``neorv32`` machine instantiates the MIPI CSI-2 TX AXI4-Lite IP
(``mipi_tx_axi_ip``) on the external bus at ``0x44A00000``. Build
``sw/example/demo_mipi_tx`` from the NEORV32 tree, or use the prebuilt
``binaries/examples/demo_mipi_tx/neorv32_exe.bin`` bundled here.

```bash
./scripts/bash/generate_flash_image.sh \
    -p binaries/examples/demo_mipi_tx/neorv32_exe.bin \
    -o binaries/flash_images/flash_demo_mipi_tx_64mb.bin

./scripts/bash/run_with_flash.sh \
    -q $HOME/qemu/build/qemu-system-riscv32 \
    -f binaries/flash_images/flash_demo_mipi_tx_64mb.bin
```

The demo transmits four 640x480 RAW10 frames over two lanes and prints one
line per frame. The device can also capture the generated CSI-2 packet stream
to a file. The type name contains a dot, so the long ``-global`` syntax has to
be used:

```bash
./scripts/bash/run_with_flash.sh \
    -q $HOME/qemu/build/qemu-system-riscv32 \
    -f binaries/flash_images/flash_demo_mipi_tx_64mb.bin \
    -- -global driver=neorv32.mipi-tx,property=dumpfile,value=/tmp/mipi_tx.bin
```

The resulting file holds back-to-back CSI-2 packets (Frame Start short packet,
one long packet per line with header ECC and payload CRC, Frame End short
packet) and can be fed to the `mipi_decoder` tooling:

```bash
mipi-decoder decode /tmp/mipi_tx.bin --frame-summary
mipi-decoder decode /tmp/mipi_tx.bin --export-raw10-png-dir /tmp/frames
```

#### Machine-specific options

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

  * In another shell:
```bash
  $ riscv32-unknown-elf-gdb /path/to/neorv32/bootloader/main.elf
  (gdb) target remote :1234
```

#### Known limitations


This is a functional model intended for software bring-up and testing of  
example programs. It may not model all timing details or every optional  
peripheral available in a specific NEORV32 SoC configuration.  





