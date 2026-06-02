/*
 * GPS LoRa Receiver — Relais NMEA vers Serial USB
 *
 * Reçoit les trames $GPRMC/$GNRMC transmises par gps_lora_logger.ino
 * via LoRa et les relaie vers le port Serial USB (115200 baud) pour
 * exploitation sur PC : GPS Viewer, terminal, script Python, etc.
 *
 * Les lignes commençant par '#' sont des diagnostics (RSSI, compteur) ;
 * un parseur NMEA standard les ignore.
 *
 * Bibliothèque requise : RadioHead (Mike McCaulay)
 *
 * ── Câblage module LoRa (interface UART) ─────────────────────────────
 *
 *   AVR (Uno/Nano) :
 *     LoRa TX --> pin 5  (RX Arduino) — connecteur Grove D5, fil jaune
 *     LoRa RX --> pin 6  (TX Arduino) — connecteur Grove D5, fil blanc
 *
 *   RP2040 / RP2350 / XIAO RA4M1 :
 *     LoRa TX --> D7  (RX)
 *     LoRa RX --> D6  (TX)
 *
 *   ESP32 C3/C6/S3 / SAMD / STM32F4 / nRF52840 :
 *     LoRa TX --> RX du Serial1 matériel
 *     LoRa RX --> TX du Serial1 matériel
 *
 *   LoRa VCC --> 3.3 V  |  LoRa GND --> GND
 */

#include <RH_RF95.h>

#ifdef __AVR__
    #include <SoftwareSerial.h>
    SoftwareSerial SSerial(5, 6);   // RX=5 (LoRa TX), TX=6 (LoRa RX) — connecteur Grove D5
    #define COMSerial SSerial
    #define ShowSerial Serial
    RH_RF95<SoftwareSerial> rf95(COMSerial);
#endif

#if defined(ARDUINO_ARCH_RP2040) || defined(ARDUINO_ARCH_RP2350) || defined(ARDUINO_XIAO_RA4M1)
    #include <SoftwareSerial.h>
    SoftwareSerial SSerial(D7, D6);
    #define COMSerial SSerial
    #define ShowSerial Serial
    RH_RF95<SoftwareSerial> rf95(COMSerial);
#endif

#if defined(CONFIG_IDF_TARGET_ESP32C3) || defined(CONFIG_IDF_TARGET_ESP32C6) || defined(CONFIG_IDF_TARGET_ESP32S3)
    #define COMSerial Serial1
    #define ShowSerial Serial
    RH_RF95<HardwareSerial> rf95(COMSerial);
#endif

#ifdef SEEED_XIAO_M0
    #define COMSerial Serial1
    #define ShowSerial Serial
    RH_RF95<Uart> rf95(COMSerial);
#elif defined(ARDUINO_SAMD_VARIANT_COMPLIANCE)
    #define COMSerial Serial1
    #define ShowSerial SerialUSB
    RH_RF95<Uart> rf95(COMSerial);
#endif

#ifdef ARDUINO_ARCH_STM32F4
    #define COMSerial Serial
    #define ShowSerial SerialUSB
    RH_RF95<HardwareSerial> rf95(COMSerial);
#endif

#if defined(NRF52840_XXAA)
    #define COMSerial Serial1
    #define ShowSerial Serial
    RH_RF95<Uart> rf95(COMSerial);
#endif

// ── Paramètres LoRa ──────────────────────────────────────────────────
#define LORA_FREQ  434.0   // MHz — bande EU433, Grove Ra-02 (SX1278)

// ─────────────────────────────────────────────────────────────────────

uint32_t packetCount = 0;

// ─────────────────────────────────────────────────────────────────────
void setup() {
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);

    ShowSerial.begin(115200);
    ShowSerial.println(F("# GPS LoRa Receiver — en attente de trames..."));

    if (!rf95.init()) {
        ShowSerial.println(F("# ERREUR : init LoRa echouee"));
        while (1);
    }

    rf95.setFrequency(LORA_FREQ);

    ShowSerial.print(F("# LoRa OK @ "));
    ShowSerial.print(LORA_FREQ);
    ShowSerial.println(F(" MHz"));
}

// ─────────────────────────────────────────────────────────────────────
void loop() {
    if (!rf95.available()) return;

    uint8_t buf[RH_RF95_MAX_MESSAGE_LEN];
    uint8_t len = sizeof(buf);

    if (!rf95.recv(buf, &len)) {
        ShowSerial.println(F("# recv failed"));
        return;
    }

    // Validation minimale : une trame NMEA commence par '$'
    if (len < 6 || buf[0] != '$') {
        ShowSerial.println(F("# paquet ignore (non NMEA)"));
        return;
    }

    // ── Relais NMEA vers Serial USB ──
    // Le buffer contient déjà le \r\n terminal envoyé par gps_lora_logger.
    ShowSerial.write(buf, len);

    // ── Diagnostic : RSSI et compteur (ignorés par les parseurs NMEA) ──
    packetCount++;
    ShowSerial.print(F("# ["));
    ShowSerial.print(packetCount);
    ShowSerial.print(F("] RSSI: "));
    ShowSerial.print(rf95.lastRssi());
    ShowSerial.println(F(" dBm"));

    // Clignotement LED à chaque trame reçue
    digitalWrite(LED_BUILTIN, HIGH);
    delay(50);
    digitalWrite(LED_BUILTIN, LOW);
}
