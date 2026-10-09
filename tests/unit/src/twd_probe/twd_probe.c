/*
 * twd_probe - bare-metal check of the QEMU neorv32 TWD model against
 * rtl/core/neorv32_twd.vhd. Loaded with -bios at 0xFFE00000; polled, no
 * interrupts taken (the TWD IRQ line is observed in mip, FIRQ0 = bit 16).
 *
 * Driven by tests/unit/test_twd_model.py through i2c-master-chardev; every
 * step prints "PROBE: ready <step>", waits for the host transfer, checks it
 * and prints "PROBE: <step> OK" or "PROBE: FAIL <step> ...".
 */

#include <stdint.h>

#define UART0_CTRL (*(volatile uint32_t *)0xFFF50000u)
#define UART0_DATA (*(volatile uint32_t *)0xFFF50004u)
#define TWD_CTRL   (*(volatile uint32_t *)0xFFEA0000u)
#define TWD_DATA   (*(volatile uint32_t *)0xFFEA0004u)

#define EN          (1u << 0)
#define CLR_RX      (1u << 1)
#define CLR_TX      (1u << 2)
#define ADDR(a)     ((uint32_t)(a) << 4)
#define IRQ_RX_AV   (1u << 11)
#define IRQ_TX_EMP  (1u << 13)
#define IRQ_TX_NFU  (1u << 14)
#define IRQ_COM_BEG (1u << 15)
#define IRQ_COM_END (1u << 16)
#define RX_SIZE(c)  (((c) >> 17) & 0xFu)
#define TX_SIZE(c)  (((c) >> 21) & 0xFu)
#define RX_AVAIL    (1u << 25)
#define TX_EMPTY    (1u << 27)
#define TX_FULL     (1u << 28)
#define COM_BEG     (1u << 29)
#define COM_END     (1u << 30)
#define COM         (1u << 31)
#define RW_MASK     0x0001FFF9u

#define DEV_ADDR    0x32u
#define MIP_FIRQ0   (1u << 16)

static void puts_(const char *s)
{
	while (*s) {
		UART0_DATA = (uint32_t)*s++;
	}
}

static void puthex(uint32_t v)
{
	puts_("0x");
	for (int i = 28; i >= 0; i -= 4) {
		UART0_DATA = (uint32_t)"0123456789ABCDEF"[(v >> i) & 0xF];
	}
}

static uint32_t mip(void)
{
	uint32_t v;

	__asm__ volatile("csrr %0, mip" : "=r"(v));
	return v;
}

static int fail(const char *step, uint32_t value)
{
	puts_("PROBE: FAIL ");
	puts_(step);
	puts_(" ");
	puthex(value);
	puts_(" ctrl=");
	puthex(TWD_CTRL);
	puts_("\nPROBE: end\n");
	for (;;) {
	}
	return 0;
}

static void ok(const char *step)
{
	puts_("PROBE: ");
	puts_(step);
	puts_(" OK\n");
}

static void ready(const char *step)
{
	puts_("PROBE: ready ");
	puts_(step);
	puts_("\n");
}

/* Wait for the end of a transfer addressed to us. */
static uint32_t wait_com_end(void)
{
	uint32_t c;

	do {
		c = TWD_CTRL;
	} while ((c & COM_END) == 0);
	return c;
}

static void ack_com(uint32_t cfg)
{
	TWD_CTRL = cfg | COM_BEG | COM_END;
}

int main(void)
{
	uint32_t cfg = EN | ADDR(DEV_ADDR);
	uint32_t c;

	UART0_CTRL = 1;
	puts_("PROBE: start\n");

	/* ---- layout ---------------------------------------------------- */
	TWD_CTRL = 0;
	TWD_CTRL = cfg | CLR_RX | CLR_TX;
	c = TWD_CTRL;
	if ((c & RW_MASK) != cfg) {
		return fail("layout-rw", c);
	}
	if (RX_SIZE(c) != 4 || TX_SIZE(c) != 4) {
		return fail("layout-fifo-size", c);
	}
	if ((c & (TX_EMPTY | RX_AVAIL | TX_FULL | COM_BEG | COM_END | COM)) != TX_EMPTY) {
		return fail("layout-status", c);
	}
	ok("layout");

	/* ---- interrupt sources ----------------------------------------- */
	if (mip() & MIP_FIRQ0) {
		return fail("irq-idle", mip());
	}
	TWD_CTRL = cfg | IRQ_TX_EMP;
	if (!(mip() & MIP_FIRQ0)) {
		return fail("irq-tx-empty", mip());
	}
	TWD_CTRL = cfg | IRQ_TX_NFU;
	if (!(mip() & MIP_FIRQ0)) {
		return fail("irq-tx-nfull", mip());
	}
	for (int i = 0; i < 16; i++) {
		TWD_DATA = 0xEE;
	}
	if (!(TWD_CTRL & TX_FULL) || (mip() & MIP_FIRQ0)) {
		return fail("irq-tx-full", mip());
	}
	TWD_CTRL = cfg | CLR_TX;
	if (mip() & MIP_FIRQ0) {
		return fail("irq-off", mip());
	}
	ok("irq");

	/* ---- write: COM_BEG / COM_END, W1C, RX data --------------------- */
	cfg |= IRQ_COM_BEG | IRQ_COM_END;
	TWD_CTRL = cfg;
	TWD_DATA = 0xA0;
	TWD_DATA = 0xA1;
	TWD_DATA = 0xA2;
	TWD_DATA = 0xA3;
	ready("write");
	c = wait_com_end();
	if (!(c & COM_BEG) || (c & COM)) {
		return fail("write-flags", c);
	}
	if (!(mip() & MIP_FIRQ0)) {
		return fail("write-irq", mip());
	}
	if ((TWD_DATA & 0xFF) != 0x11 || (TWD_DATA & 0xFF) != 0x22 ||
	    (TWD_CTRL & RX_AVAIL)) {
		return fail("write-rx", TWD_CTRL);
	}
	TWD_CTRL = c & RW_MASK; /* flags written as 0: must stay set */
	c = TWD_CTRL;
	if ((c & (COM_BEG | COM_END)) != (COM_BEG | COM_END)) {
		return fail("write-w0-keeps", c);
	}
	TWD_CTRL = cfg | COM_BEG; /* clear BEG only */
	c = TWD_CTRL;
	if ((c & (COM_BEG | COM_END)) != COM_END || !(mip() & MIP_FIRQ0)) {
		return fail("write-w1c-beg", c);
	}
	TWD_CTRL = cfg | COM_END;
	c = TWD_CTRL;
	if ((c & (COM_BEG | COM_END)) || (mip() & MIP_FIRQ0)) {
		return fail("write-w1c-end", c);
	}
	ok("write");

	/* ---- reads: TX head popped only on the master's ACK ------------- */
	ready("read1");      /* host reads 2: A0 A1, A1 NACKed stays */
	wait_com_end();
	ack_com(cfg);
	ok("read1");
	ready("read2");      /* host reads 2: A1 A2 */
	wait_com_end();
	ack_com(cfg);
	ok("read2");
	ready("read3");      /* host reads 3: A2 A3 FF, FIFO drained */
	wait_com_end();
	ack_com(cfg);
	if (!(TWD_CTRL & TX_EMPTY)) {
		return fail("read3-empty", TWD_CTRL);
	}
	ok("read3");

	/* ---- foreign address: no flags, no data ------------------------- */
	ready("nack");       /* host: R 0x33 (NACK), then W 0x32 1 0x5A */
	c = wait_com_end();
	if ((TWD_DATA & 0xFF) != 0x5A || (TWD_CTRL & RX_AVAIL)) {
		return fail("nack-rx", c);
	}
	ack_com(cfg);
	ok("nack");

	/* ---- disabling clears the flags --------------------------------- */
	ready("disable");    /* host: W 0x32 1 0x01 */
	wait_com_end();
	TWD_CTRL = 0;
	TWD_CTRL = cfg;
	c = TWD_CTRL;
	if (c & (COM_BEG | COM_END | RX_AVAIL)) {
		return fail("disable", c);
	}
	ok("disable");

	puts_("PROBE: PASS\nPROBE: end\n");
	for (;;) {
	}
	return 0;
}
