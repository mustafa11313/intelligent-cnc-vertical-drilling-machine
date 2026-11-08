/* Runs daq.ino (compiled for the ATmega328P) in simavr and feeds its ADC:
     A0: mid-rail bias + a 50 Hz sine of <amp_mV> peak (the SCT-013-005 signal)
     A1: a DC level of <load_mV> (the divided VFD load signal)
   and prints what the firmware sends on its serial port for 2 s.
   Usage: ./harness daq.elf <amp_mV> <load_mV>     (build and check with run.sh) */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "sim_avr.h"
#include "sim_elf.h"
#include "avr_adc.h"
#include "avr_uart.h"

static avr_t *avr;
static avr_irq_t *adc0, *adc1;
static double amp_mv, load_mv;

static void on_trigger(struct avr_irq_t *irq, uint32_t value, void *param) {
    double t = avr->cycle / 16e6;
    avr_raise_irq(adc0, (uint32_t)(2500 + amp_mv * sin(2 * M_PI * 50 * t)));
    avr_raise_irq(adc1, (uint32_t)load_mv);
}
static void on_uart(struct avr_irq_t *irq, uint32_t value, void *param) { putchar(value); fflush(stdout); }

int main(int argc, char **argv) {
    elf_firmware_t f = {0};
    elf_read_firmware(argv[1], &f);
    amp_mv = atof(argv[2]); load_mv = atof(argv[3]);
    avr = avr_make_mcu_by_name("atmega328p");
    avr_init(avr); avr->frequency = 16000000; avr->avcc = 5000; avr->aref = 5000; avr->vcc = 5000; avr_load_firmware(avr, &f);
    adc0 = avr_io_getirq(avr, AVR_IOCTL_ADC_GETIRQ, ADC_IRQ_ADC0);
    adc1 = avr_io_getirq(avr, AVR_IOCTL_ADC_GETIRQ, ADC_IRQ_ADC1);
    avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_ADC_GETIRQ, ADC_IRQ_OUT_TRIGGER), on_trigger, NULL);
    avr_irq_register_notify(avr_io_getirq(avr, AVR_IOCTL_UART_GETIRQ('0'), UART_IRQ_OUTPUT), on_uart, NULL);
    uint32_t flags = 0;
    avr_ioctl(avr, AVR_IOCTL_UART_GET_FLAGS('0'), &flags);
    flags &= ~AVR_UART_FLAG_STDIO;
    avr_ioctl(avr, AVR_IOCTL_UART_SET_FLAGS('0'), &flags);
    while (avr->cycle < 16000000ULL * 2 && avr->state != cpu_Done && avr->state != cpu_Crashed) avr_run(avr);
    return 0;
}
