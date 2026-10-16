/*
 * i2c_target_probe - bare-metal "firmware" for the QEMU neorv32.i2c-target
 * model (i2c_target_ip). Loaded with -bios at 0xFFE00000; driven by
 * tests/unit/test_i2c_target_model.py through i2c-master-chardev.
 *
 * Serves the camera device set of i2c_target_ip/tests/scenarios:
 *   0x54..0x57  EEPROM n: 256 bytes, byte i = i ^ (0x5A + 0x11*n), writable,
 *               write [ptr, data...], reads continue at ptr (8-bit wrap)
 *   0x36        OV5693: 16-bit big-endian sub-address, auto-increment,
 *               0x3D00..02 read AB CD EF; backing store aliases addr & 0x1FFF
 *   0x5F        probe control / statistics: write 0xDD = stop serving for
 *               200 ms (watchdog test); reads return
 *               [txreq lo, txreq hi, irq_ok, wdog count, skipped TXREQ, 0x5F]
 * The event loop is the one of the IP README (batch, TXREQ look-ahead) and
 * runs only while the machine external interrupt (mip.MEIP, bit 11) is set,
 * which checks the OR of the XBUS interrupts.
 */

#include <stdint.h>

#define UART0_CTRL (*(volatile uint32_t *)0xFFF50000u)
#define UART0_DATA (*(volatile uint32_t *)0xFFF50004u)
#define MTIME_LO   (*(volatile uint32_t *)0xFFF4BFF8u)

#define I2CT_BASE  0x44A10000u
#define REG(off)   (*(volatile uint32_t *)(I2CT_BASE + (off)))
#define R_ID         0x00
#define R_CTRL       0x0C
#define R_IRQ_STATUS 0x14
#define R_IRQ_ENABLE 0x18
#define R_EVENT      0x1C
#define R_TX_DATA    0x20
#define R_TIMEOUT    0x34
#define R_SLOT(n)    (0x40 + 4 * (n))

#define EV_START 1
#define EV_RX    2
#define EV_TXREQ 3
#define EV_STOP  4
#define EV_WDOG  5

#define MIP_MEIP (1u << 11)

static uint8_t eeprom[4][256];
static uint8_t ov[8192];
static uint8_t ee_ptr[4];
static uint16_t ov_ptr;
static int wcount;
static uint8_t stats_ptr;
static uint32_t n_txreq, n_wdog, n_skipped;
static int irq_ok;
static int dead_pending;
static uint32_t batch[64];

static void puts_(const char *s)
{
    while (*s) {
        UART0_DATA = (uint32_t)*s++;
    }
}

static uint32_t mip(void)
{
    uint32_t v;

    __asm__ volatile("csrr %0, mip" : "=r"(v));
    return v;
}

static void delay_ms(uint32_t ms)
{
    uint32_t t0 = MTIME_LO;

    while (MTIME_LO - t0 < ms * 100000u) {
    }
}

static uint8_t stats_byte(uint8_t i)
{
    switch (i) {
    case 0: return (uint8_t)n_txreq;
    case 1: return (uint8_t)(n_txreq >> 8);
    case 2: return (uint8_t)irq_ok;
    case 3: return (uint8_t)n_wdog;
    case 4: return (uint8_t)n_skipped;
    default: return 0x5F;
    }
}

static uint8_t dev_read(int slot)
{
    uint8_t v;

    if (slot < 4) {
        return eeprom[slot][ee_ptr[slot]++];
    }
    if (slot == 4) {
        if (ov_ptr == 0x3D00) v = 0xAB;
        else if (ov_ptr == 0x3D01) v = 0xCD;
        else if (ov_ptr == 0x3D02) v = 0xEF;
        else v = ov[ov_ptr & 0x1FFF];
        ov_ptr++;
        return v;
    }
    return stats_byte(stats_ptr++);
}

static void dev_write(int slot, uint8_t b)
{
    if (slot < 4) {
        if (wcount == 0) ee_ptr[slot] = b;
        else eeprom[slot][ee_ptr[slot]++] = b;
    } else if (slot == 4) {
        if (wcount == 0) ov_ptr = (uint16_t)((b << 8) | (ov_ptr & 0xFF));
        else if (wcount == 1) ov_ptr = (uint16_t)((ov_ptr & 0xFF00) | b);
        else ov[(ov_ptr++) & 0x1FFF] = b;
    } else if (b == 0xDD) {
        dead_pending = 1;
    }
    wcount++;
}

int main(void)
{
    UART0_CTRL = 1;
    irq_ok = 1;
    n_txreq = n_wdog = n_skipped = 0;
    dead_pending = 0;
    stats_ptr = 0;
    ov_ptr = 0;
    for (int n = 0; n < 4; n++) {
        ee_ptr[n] = 0;
        for (int i = 0; i < 256; i++) {
            eeprom[n][i] = (uint8_t)(i ^ (0x5A + 0x11 * n));
        }
    }
    for (int i = 0; i < 8192; i++) {
        ov[i] = 0;
    }
    if (REG(R_ID) != 0x49324354u) {
        puts_("PROBE: FAIL id\nPROBE: end\n");
        for (;;) {
        }
    }
    for (int n = 0; n < 4; n++) {
        REG(R_SLOT(n)) = 0x80000000u | (0x54u + n);
    }
    REG(R_SLOT(4)) = 0x80000036u;
    REG(R_SLOT(5)) = 0x8000005Fu;
    REG(R_TIMEOUT) = 2000000;       /* 20 ms watchdog (virtual time = host time) */
    REG(R_IRQ_ENABLE) = 0x3;        /* EVT + WDOG */
    REG(R_CTRL) = 1;
    if (mip() & MIP_MEIP) {
        irq_ok = 0;                 /* no event yet: the line must be low */
    }
    puts_("PROBE: ready\n");

    for (;;) {
        int n = 0;

        while (!(mip() & MIP_MEIP)) {
        }
        if (!(REG(R_IRQ_STATUS) & 0x3)) {
            irq_ok = 0;             /* line high without a reason */
        }
        REG(R_IRQ_STATUS) = 0x2;    /* acknowledge WDOG */
        for (;;) {
            uint32_t ev = REG(R_EVENT);

            if (!(ev >> 31)) {
                break;
            }
            if (n < 64) {
                batch[n++] = ev;
            }
        }
        for (int i = 0; i < n; i++) {
            uint32_t ev = batch[i];
            int type = (ev >> 24) & 0xF;
            int slot = (ev >> 16) & 0x7;

            switch (type) {
            case EV_START:
                if (!((ev >> 15) & 1)) {
                    wcount = 0;
                } else if (slot == 5) {
                    stats_ptr = 0;
                }
                break;
            case EV_RX:
                dev_write(slot, (uint8_t)ev);
                break;
            case EV_TXREQ: {
                int stale = 0;

                for (int k = i + 1; k < n; k++) {
                    int t = (batch[k] >> 24) & 0xF;

                    if (t == EV_WDOG || t == EV_STOP || t == EV_START) {
                        stale = 1;
                    }
                }
                if (stale) {
                    n_skipped++;
                } else {
                    n_txreq++;
                    REG(R_TX_DATA) = dev_read(slot);
                }
                break;
            }
            case EV_WDOG:
                n_wdog++;
                break;
            case EV_STOP:
                if (dead_pending) {
                    dead_pending = 0;
                    delay_ms(200);
                }
                break;
            default:
                break;
            }
        }
    }
    return 0;
}
