/* Bare-metal entry for twd_probe: stack at the top of DMEM, then main(). */
    .section .text.start
    .globl _start
_start:
    li    sp, 0x80008000
    call  main
1:  j     1b
