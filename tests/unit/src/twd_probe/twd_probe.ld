OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
  rom (rx)  : ORIGIN = 0xFFE00000, LENGTH = 8K
  ram (rw)  : ORIGIN = 0x80000000, LENGTH = 32K
}
SECTIONS {
  .text   : { *(.text.start) *(.text*) } > rom
  .rodata : { *(.rodata*) *(.srodata*) } > rom
  /DISCARD/ : { *(.data*) *(.sdata*) *(.bss*) *(.sbss*) *(.comment) }
}
