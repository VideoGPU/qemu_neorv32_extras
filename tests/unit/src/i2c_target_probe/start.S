/* Bare-metal entry for i2c_target_probe: stack at the top of DMEM, clear
 * .bss, then main(). The probe has no initialised data. */
    .section .text.start
    .globl _start
_start:
    li    sp, 0x80008000
    la    t0, __bss_start
    la    t1, __bss_end
2:  bgeu  t0, t1, 3f
    sw    zero, 0(t0)
    addi  t0, t0, 4
    j     2b
3:
    call  main
1:  j     1b
