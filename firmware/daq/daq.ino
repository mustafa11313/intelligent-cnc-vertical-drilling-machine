/*
  CNC drilling machine - DAQ board firmware (Arduino Nano, ATmega328P)

  Measures and reports 10 times per second:
    - spindle supply current, true RMS     (SCT-013 + LM358 stage on A0)
    - 2x temperature                        (DS18B20 on one 1-Wire bus, A2)
    - acceleration x/y/z + vibration RMS    (ADXL345 on I2C, A4/A5)

  Output line (115200 baud), parsed by app/daq.py:
    D,<ms>,<I_A>,<T1_C>,<T2_C>,<ax_g>,<ay_g>,<az_g>,<vib_g>*<XX>
  XX = XOR of all characters from 'D' up to (not including) '*', in hex.
  A sensor that is missing or failed is reported as "nan". Values are
  never invented or smoothed with random numbers.

  Serial commands (end with newline):
    I            print identity and sensor summary
    K<value>     set current calibration in A per ADC-volt RMS (stored in EEPROM)
    K            print current calibration

  Why it is written this way:
    * Current: the ADC runs free (9.6 kHz) and an interrupt adds up the
      samples and their squares. RMS = standard deviation over the 100 ms
      window (5 mains cycles at 50 Hz), so the DC bias of the op-amp stage
      cancels by itself and no offset calibration is needed.
    * Vibration: the ADXL345 samples at 1600 Hz into its 32-entry FIFO. We
      empty the FIFO in bursts, so the 1-Wire temperature reads (which
      block for ~10 ms) never lose accelerometer samples. 1600 Hz covers
      the spindle's rotation frequency (18000 rpm = 300 Hz); the old 100 Hz
      style polling could not see it.
    * Temperature: DS18B20 conversions take 750 ms, so they run in the
      background: start conversion, come back 750 ms later, read both.
  No external libraries are needed (only Wire and EEPROM from the core).
*/

#include <Arduino.h>
#include <Wire.h>
#include <EEPROM.h>
#include <math.h>

// ----------------------------------------------------------------- pins
#define PIN_CURRENT      A0     // LM358 output (SCT-013 signal, biased to mid-rail)
#define PIN_ONEWIRE      A2     // DS18B20 data, 4.7k pull-up to 5V
#define ADXL345_ADDR     0x53   // SDO tied low (0x1D if SDO high)

// ----------------------------------------------------------------- settings
#define REPORT_MS        100
#define FW_NAME          "CNC-DAQ"
#define FW_VERSION       "2.0"
#define EEPROM_MAGIC     0xC7A1
// Default current calibration: amps per volt RMS at the ADC pin.
// SCT-013-100 (100 A : 50 mA) into a 33 ohm burden gives 1.65 V at 100 A,
// i.e. 60.6 A/V, divided by the LM358 stage gain (set this to your circuit).
// Calibrate with a known load and the K command (see calibration guide).
#define DEFAULT_A_PER_V  60.6f

// ===================================================================== current
volatile uint16_t adc_n = 0;
volatile uint32_t adc_sum = 0;
volatile uint32_t adc_sumsq = 0;
float amps_per_volt = DEFAULT_A_PER_V;

ISR(ADC_vect) {
  uint16_t v = ADC;
  if (adc_n < 4000) {          // keeps sumsq inside 32 bits (4000*1023^2 < 2^32)
    adc_n++;
    adc_sum += v;
    adc_sumsq += (uint32_t)v * v;
  }
}

void adc_start_free_running(uint8_t pin) {
  uint8_t ch = pin - A0;
  ADMUX = _BV(REFS0) | (ch & 0x07);                 // AVcc reference, channel
  ADCSRB = 0;                                       // free running trigger
  ADCSRA = _BV(ADEN) | _BV(ADSC) | _BV(ADATE) | _BV(ADIE) |
           _BV(ADPS2) | _BV(ADPS1) | _BV(ADPS0);    // prescaler 128 -> 9.6 kHz
}

// Returns RMS current in A, or NAN if the window was too short.
float current_take_rms() {
  uint16_t n;
  uint32_t s, sq;
  noInterrupts();
  n = adc_n; s = adc_sum; sq = adc_sumsq;
  adc_n = 0; adc_sum = 0; adc_sumsq = 0;
  interrupts();
  if (n < 50) return NAN;
  float mean = (float)s / n;
  float var = (float)sq / n - mean * mean;          // counts^2
  if (var < 0) var = 0;
  float v_rms = sqrt(var) * (5.0f / 1023.0f);
  return v_rms * amps_per_volt;
}

// ===================================================================== 1-Wire
// Minimal 1-Wire master (bit-banged, standard speed) + ROM search.
static inline void ow_low()     { pinMode(PIN_ONEWIRE, OUTPUT); digitalWrite(PIN_ONEWIRE, LOW); }
static inline void ow_release() { pinMode(PIN_ONEWIRE, INPUT); }

bool ow_reset() {
  ow_release();
  delayMicroseconds(5);
  if (!digitalRead(PIN_ONEWIRE)) return false;   // bus stuck low: shorted or no pull-up
  ow_low();
  delayMicroseconds(480);
  noInterrupts();
  ow_release();
  delayMicroseconds(70);
  bool present = !digitalRead(PIN_ONEWIRE);
  interrupts();
  delayMicroseconds(410);
  return present;
}

void ow_write_bit(uint8_t b) {
  noInterrupts();
  ow_low();
  if (b) { delayMicroseconds(6);  ow_release(); interrupts(); delayMicroseconds(64); }
  else   { delayMicroseconds(60); ow_release(); interrupts(); delayMicroseconds(10); }
}

uint8_t ow_read_bit() {
  noInterrupts();
  ow_low();
  delayMicroseconds(3);
  ow_release();
  delayMicroseconds(10);
  uint8_t r = digitalRead(PIN_ONEWIRE);
  interrupts();
  delayMicroseconds(53);
  return r;
}

void ow_write(uint8_t v) { for (uint8_t i = 0; i < 8; i++) { ow_write_bit(v & 1); v >>= 1; } }
uint8_t ow_read() { uint8_t v = 0; for (uint8_t i = 0; i < 8; i++) { if (ow_read_bit()) v |= 1 << i; } return v; }

uint8_t crc8(const uint8_t *d, uint8_t len) {
  uint8_t crc = 0;
  while (len--) {
    uint8_t in = *d++;
    for (uint8_t i = 0; i < 8; i++) {
      uint8_t mix = (crc ^ in) & 1;
      crc >>= 1;
      if (mix) crc ^= 0x8C;
      in >>= 1;
    }
  }
  return crc;
}

#define MAX_SENSORS 2
uint8_t rom[MAX_SENSORS][8];
uint8_t n_sensors = 0;

// Maxim AN187 search algorithm: finds every device ROM on the bus.
uint8_t ow_search_all() {
  uint8_t found = 0;
  uint8_t last_discrepancy = 0;
  bool last_device = false;
  uint8_t id[8] = {0};
  uint8_t passes = 0;
  // The pass limit guards against a faulty bus making the search loop forever.
  while (!last_device && found < MAX_SENSORS && passes++ < 4 * MAX_SENSORS) {
    if (!ow_reset()) break;
    ow_write(0xF0);                            // SEARCH ROM
    uint8_t last_zero = 0;
    for (uint8_t bit = 1; bit <= 64; bit++) {
      uint8_t byte = (bit - 1) / 8, mask = 1 << ((bit - 1) % 8);
      uint8_t a = ow_read_bit(), b = ow_read_bit();
      uint8_t dir;
      if (a && b) return found;                  // no devices responding
      if (a != b) dir = a;
      else {
        if (bit < last_discrepancy) dir = (id[byte] & mask) ? 1 : 0;
        else dir = (bit == last_discrepancy);
        if (!dir) last_zero = bit;
      }
      if (dir) id[byte] |= mask; else id[byte] &= ~mask;
      ow_write_bit(dir);
    }
    last_discrepancy = last_zero;
    if (last_discrepancy == 0) last_device = true;
    if (crc8(id, 7) == id[7] && id[0] == 0x28) {   // 0x28 = DS18B20 family
      memcpy(rom[found], id, 8);
      found++;
    }
  }
  return found;
}

float temps[MAX_SENSORS] = {NAN, NAN};
uint32_t conv_started = 0;
bool converting = false;

void ds_start_conversion() {
  if (!ow_reset()) { for (uint8_t i = 0; i < MAX_SENSORS; i++) temps[i] = NAN; return; }
  ow_write(0xCC);                              // SKIP ROM: all sensors at once
  ow_write(0x44);                              // CONVERT T
  conv_started = millis();
  converting = true;
}

float ds_read(uint8_t i) {
  if (!ow_reset()) return NAN;
  ow_write(0x55);                              // MATCH ROM
  for (uint8_t k = 0; k < 8; k++) ow_write(rom[i][k]);
  ow_write(0xBE);                              // READ SCRATCHPAD
  uint8_t sp[9];
  for (uint8_t k = 0; k < 9; k++) sp[k] = ow_read();
  if (crc8(sp, 8) != sp[8]) return NAN;
  int16_t raw = (int16_t)((sp[1] << 8) | sp[0]);
  float t = raw / 16.0f;
  if (t == 85.0f || t < -55.0f || t > 125.0f) return NAN;   // 85.0 = power-on value, not a reading
  return t;
}

void temps_service() {
  if (converting && millis() - conv_started >= 760) {
    for (uint8_t i = 0; i < MAX_SENSORS; i++) temps[i] = (i < n_sensors) ? ds_read(i) : NAN;
    converting = false;
  }
  if (!converting && n_sensors) ds_start_conversion();
}

// ===================================================================== ADXL345
bool adxl_ok = false;
const float G_PER_LSB = 0.0039f;               // full resolution mode
float acc_sum[3], acc_sumsq[3];
uint16_t acc_n = 0;

void adxl_write(uint8_t reg, uint8_t v) {
  Wire.beginTransmission(ADXL345_ADDR); Wire.write(reg); Wire.write(v); Wire.endTransmission();
}

uint8_t adxl_read8(uint8_t reg) {
  Wire.beginTransmission(ADXL345_ADDR); Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return 0xFF;
  Wire.requestFrom((uint8_t)ADXL345_ADDR, (uint8_t)1);
  return Wire.available() ? Wire.read() : 0xFF;
}

bool adxl_init() {
  if (adxl_read8(0x00) != 0xE5) return false;  // DEVID
  adxl_write(0x2D, 0x00);                      // standby while configuring
  adxl_write(0x31, 0x0B);                      // full resolution, +/-16 g
  adxl_write(0x2C, 0x0E);                      // 1600 Hz output data rate
  adxl_write(0x38, 0x80);                      // FIFO stream mode
  adxl_write(0x2D, 0x08);                      // measure
  return true;
}

void adxl_service() {
  if (!adxl_ok) return;
  uint8_t entries = adxl_read8(0x39) & 0x3F;   // FIFO_STATUS
  if (entries == 0x3F) { adxl_ok = adxl_init(); return; }   // bus error: re-init
  while (entries--) {
    Wire.beginTransmission(ADXL345_ADDR); Wire.write(0x32);
    if (Wire.endTransmission(false) != 0) { adxl_ok = false; return; }
    Wire.requestFrom((uint8_t)ADXL345_ADDR, (uint8_t)6);
    if (Wire.available() < 6) { adxl_ok = false; return; }
    int16_t v[3];
    for (uint8_t k = 0; k < 3; k++) { uint8_t lo = Wire.read(); v[k] = (int16_t)(Wire.read() << 8 | lo); }
    for (uint8_t k = 0; k < 3; k++) {
      float g = v[k] * G_PER_LSB;
      acc_sum[k] += g;
      acc_sumsq[k] += g * g;
    }
    acc_n++;
  }
}

// ===================================================================== report
char line[112];
uint8_t pos;

void put(const char *s) { while (*s && pos < sizeof(line) - 4) line[pos++] = *s++; }
void put_float(float v, uint8_t digits) {
  char buf[16];
  if (isnan(v)) { put("nan"); return; }
  dtostrf(v, 1, digits, buf);
  put(buf);
}

void report() {
  float amps = current_take_rms();
  float mean[3] = {NAN, NAN, NAN}, vib = NAN;
  if (adxl_ok && acc_n >= 4) {
    float var = 0;
    for (uint8_t k = 0; k < 3; k++) {
      mean[k] = acc_sum[k] / acc_n;
      float vk = acc_sumsq[k] / acc_n - mean[k] * mean[k];
      if (vk > 0) var += vk;
    }
    vib = sqrt(var);                           // total AC acceleration, g rms
  }
  for (uint8_t k = 0; k < 3; k++) { acc_sum[k] = 0; acc_sumsq[k] = 0; }
  acc_n = 0;

  char num[12];
  pos = 0;
  put("D,");
  ultoa(millis(), num, 10); put(num); put(",");
  put_float(amps, 3); put(",");
  put_float(temps[0], 2); put(",");
  put_float(temps[1], 2); put(",");
  put_float(mean[0], 4); put(",");
  put_float(mean[1], 4); put(",");
  put_float(mean[2], 4); put(",");
  put_float(vib, 4);
  uint8_t cs = 0;
  for (uint8_t i = 0; i < pos; i++) cs ^= line[i];
  line[pos] = 0;
  Serial.print(line);
  Serial.print('*');
  if (cs < 16) Serial.print('0');
  Serial.println(cs, HEX);
}

void identify() {
  Serial.print(F("#DAQ," FW_NAME "," FW_VERSION "\r\n"));
  Serial.print(F("#INFO,ds18b20=")); Serial.print(n_sensors);
  Serial.print(F(",adxl345=")); Serial.print(adxl_ok ? 1 : 0);
  Serial.print(F(",a_per_v=")); Serial.println(amps_per_volt, 4);
}

// ===================================================================== commands
char cmd[24];
uint8_t cmd_len = 0;

void handle_command() {
  cmd[cmd_len] = 0;
  if (cmd[0] == 'I') identify();
  else if (cmd[0] == 'K') {
    if (cmd[1]) {
      float k = atof(cmd + 1);
      if (k > 0 && k < 10000) {
        amps_per_volt = k;
        EEPROM.put(0, (uint16_t)EEPROM_MAGIC);
        EEPROM.put(2, amps_per_volt);
      }
    }
    Serial.print(F("#INFO,a_per_v=")); Serial.println(amps_per_volt, 4);
  }
  cmd_len = 0;
}

void serial_service() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') { if (cmd_len) handle_command(); }
    else if (cmd_len < sizeof(cmd) - 1) cmd[cmd_len++] = c;
  }
}

// ===================================================================== main
uint32_t next_report;

void setup() {
  Serial.begin(115200);
  uint16_t magic;
  EEPROM.get(0, magic);
  if (magic == EEPROM_MAGIC) {
    float k; EEPROM.get(2, k);
    if (k > 0 && k < 10000) amps_per_volt = k;
  }
  Wire.begin();
  Wire.setClock(400000);
  // Without a timeout a missing ADXL345 or a noisy I2C line can hang the
  // old Wire library forever (needs Arduino AVR core 1.8.3 or newer).
  Wire.setWireTimeout(3000, true);
  adxl_ok = adxl_init();
  n_sensors = ow_search_all();
  identify();
  adc_start_free_running(PIN_CURRENT);
  if (n_sensors) ds_start_conversion();
  next_report = millis() + REPORT_MS;
}

void loop() {
  serial_service();
  adxl_service();
  temps_service();
  if ((int32_t)(millis() - next_report) >= 0) {
    next_report += REPORT_MS;
    report();
  }
}
