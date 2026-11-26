// Outpost 2.0 bring-up check for the Heltec V4-R8: PSRAM size, OLED power, SX1262 init.
// Transmits nothing. 915 MHz (US). Check pins against the V4-R8 schematic first.
#include <Arduino.h>
#include <RadioLib.h>

static SX1262 radio = new Module(SS, DIO0, RST_LoRa, BUSY_LoRa);

void setup() {
  Serial.begin(115200);
  pinMode(Vext, OUTPUT);
  digitalWrite(Vext, LOW);  // Vext on (powers OLED / GNSS header)
  pinMode(LED, OUTPUT);
  delay(200);
  Serial.printf("PSRAM: %u bytes\n", static_cast<unsigned>(ESP.getPsramSize()));
  const int state = radio.begin(915.0F);
  Serial.printf("SX1262 begin: %d\n", state);
}

void loop() {
  static uint32_t last = 0;
  if (millis() - last >= 1000U) {
    last = millis();
    digitalWrite(LED, !digitalRead(LED));
  }
}
