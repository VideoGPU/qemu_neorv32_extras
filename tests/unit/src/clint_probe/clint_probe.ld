OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { rom (rx) : ORIGIN = 0xFFE00000, LENGTH = 8K }
SECTIONS {
  .text   : { *(.text*) } > rom
  .rodata : { *(.rodata*) } > rom
}
