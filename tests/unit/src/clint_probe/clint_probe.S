/* Bare-metal probe for -M neorv32: priv-1.12 CSR + CLINT MTIME/MTIMECMP/MTIP.
 * Loaded with -bios at 0xFFE00000. Prints one line per check on UART0. */
    .equ UART0,    0xFFF50000
    .equ MTIMECMP, 0xFFF44000
    .equ MTIME,    0xFFF4BFF8

    .section .text
    .globl _start
_start:
    la    t0, trap
    csrw  mtvec, t0
    li    s0, UART0
    li    t0, 1
    sw    t0, 0(s0)                 /* UART0 CTRL.EN */
    la    a0, s_start
    call  puts

    /* check 1: mcountinhibit (priv >= 1.11) */
    li    s1, 0
    csrw  mcountinhibit, zero
    bnez  s1, 1f
    la    a0, s_mci_ok
    call  puts
    j     2f
1:  la    a0, s_mci_fail
    call  puts
    call  putcause
2:
    /* check 2: MTIME is mapped and advancing */
    li    s1, 0
    li    s2, MTIME
    lw    t1, 0(s2)
    bnez  s1, mt_fail
    li    t0, 20000
3:  addi  t0, t0, -1
    bnez  t0, 3b
    lw    t2, 0(s2)
    beq   t1, t2, mt_stuck
    la    a0, s_mt_ok
    call  puts

    /* check 3: MTIMECMP raises MTIP (mcause 0x80000007) */
    li    s3, MTIMECMP
    li    t0, -1
    sw    t0, 4(s3)
    lw    t1, 0(s2)
    lw    t3, 4(s2)
    li    t0, 1000
    add   t1, t1, t0
    sw    t1, 0(s3)
    sw    t3, 4(s3)
    li    s1, 0
    li    t0, 0x80
    csrs  mie, t0
    csrsi mstatus, 8
    li    t0, 50000000
4:  bnez  s1, 5f
    addi  t0, t0, -1
    bnez  t0, 4b
    la    a0, s_irq_fail
    call  puts
    j     done
5:  li    t0, 0x80000007
    bne   s1, t0, 6f
    la    a0, s_irq_ok
    call  puts
    la    a0, s_pass
    call  puts
    j     done
6:  la    a0, s_irq_wrong
    call  puts
    call  putcause
    j     done

mt_fail:
    la    a0, s_mt_fault
    call  puts
    call  putcause
    j     done
mt_stuck:
    la    a0, s_mt_stuck
    call  puts
done:
    la    a0, s_end
    call  puts
7:  wfi
    j     7b

/* sync exception: record mcause in s1, skip the 4-byte faulting insn.
 * interrupt: record mcause in s1, mask MTIE so it does not re-fire. */
    .balign 4
trap:
    csrr  s1, mcause
    bltz  s1, 1f
    csrr  t6, mepc
    addi  t6, t6, 4
    csrw  mepc, t6
    mret
1:  li    t6, 0x80
    csrc  mie, t6
    mret

puts:
    lbu   t0, 0(a0)
    beqz  t0, 1f
    sw    t0, 4(s0)
    addi  a0, a0, 1
    j     puts
1:  ret

/* print s1 as 8 hex digits + newline */
putcause:
    li    t1, 28
1:  srl   t0, s1, t1
    andi  t0, t0, 0xF
    li    t2, 10
    blt   t0, t2, 2f
    addi  t0, t0, 'A' - 10 - '0'
2:  addi  t0, t0, '0'
    sw    t0, 4(s0)
    addi  t1, t1, -4
    bgez  t1, 1b
    li    t0, '\n'
    sw    t0, 4(s0)
    ret

    .section .rodata
s_start:     .asciz "PROBE: start\n"
s_mci_ok:    .asciz "PROBE: mcountinhibit OK\n"
s_mci_fail:  .asciz "PROBE: mcountinhibit TRAP mcause=0x"
s_mt_ok:     .asciz "PROBE: mtime advancing OK\n"
s_mt_fault:  .asciz "PROBE: mtime TRAP mcause=0x"
s_mt_stuck:  .asciz "PROBE: mtime STUCK\n"
s_irq_ok:    .asciz "PROBE: mtip OK\n"
s_irq_fail:  .asciz "PROBE: mtip TIMEOUT\n"
s_irq_wrong: .asciz "PROBE: mtip WRONG mcause=0x"
s_pass:      .asciz "PROBE: PASS\n"
s_end:       .asciz "PROBE: end\n"
