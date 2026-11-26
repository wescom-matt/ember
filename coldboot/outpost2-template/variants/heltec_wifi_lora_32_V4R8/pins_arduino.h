// Heltec WiFi LoRa 32 V4-R8 (HTIT-WBR8H). Ember custom variant, NOT from Heltec or Espressif.
// Based on Arduino-ESP32 3.3.12 variants/heltec_wifi_lora_32_V4 (which matches the V4 R2 board),
// with the R8 pin changes from Heltec's V4-R8 datasheet (V4.3.1) and wiki:
//   LED GPIO35 -> GPIO46, Vext_Ctrl GPIO36 -> GPIO40, VGNSS_Ctrl -> GPIO42, PA_CTX on GPIO5.
// Check against the schematic (HTIT-WBR8H_V4.3.2.pdf in Ember's dev reference) before relying on it.
#ifndef Pins_Arduino_h
#define Pins_Arduino_h

#include <stdint.h>

#define DISPLAY_HEIGHT 64
#define DISPLAY_WIDTH  128

#define USB_VID 0x303a
#define USB_PID 0x1001

static const uint8_t LED_BUILTIN = 46;
#define BUILTIN_LED LED_BUILTIN  // backward compatibility
#define LED_BUILTIN LED_BUILTIN  // allow testing #ifdef LED_BUILTIN

static const uint8_t TX = 43;
static const uint8_t RX = 44;

static const uint8_t SDA = 3;
static const uint8_t SCL = 4;

// SX1262 on the default SPI bus
static const uint8_t SS = 8;
static const uint8_t MOSI = 10;
static const uint8_t MISO = 11;
static const uint8_t SCK = 9;

static const uint8_t A0 = 1;
static const uint8_t A1 = 2;
static const uint8_t A2 = 3;
static const uint8_t A3 = 4;
static const uint8_t A4 = 5;
static const uint8_t A5 = 6;
static const uint8_t A6 = 7;

static const uint8_t T1 = 1;
static const uint8_t T2 = 2;
static const uint8_t T3 = 3;
static const uint8_t T4 = 4;
static const uint8_t T5 = 5;
static const uint8_t T6 = 6;
static const uint8_t T7 = 7;

static const uint8_t Vext = 40;       // R8: GPIO40 (V4 R2: GPIO36)
static const uint8_t VGNSS_CTRL = 42; // R8: GPIO42
static const uint8_t PA_CTX = 5;      // R8: power amplifier control, broken out on GPIO5
static const uint8_t FEM_EN = 2;      // datasheet: GPIO2 FEM_EN
static const uint8_t VFEM_CTRL = 7;   // datasheet: GPIO7 VFEM_Control
static const uint8_t LED = 46;
static const uint8_t VBAT_READ = 1;   // ADC1_CH0

static const uint8_t RST_OLED = 21;
static const uint8_t SCL_OLED = 18;
static const uint8_t SDA_OLED = 17;

static const uint8_t RST_LoRa = 12;
static const uint8_t BUSY_LoRa = 13;
static const uint8_t DIO0 = 14;  // SX1262 DIO1

#endif /* Pins_Arduino_h */
