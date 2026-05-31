/*
 * GPS Logger + LoRa Transmitter
 *
 * Lit les trames NMEA depuis un module GPS (SoftwareSerial pins 2/3),
 * les enregistre intégralement sur carte SD (SdFat) et transmet les
 * trames $GPRMC/$GNRMC en temps réel via LoRa (RadioHead RH_RF95,
 * SoftwareSerial pins 5/6).
 *
 * Si le module LoRa est absent ou défaillant, l'enregistrement SD
 * continue normalement (dégradation gracieuse).
 *
 * Bibliothèques requises :
 *   - SdFat     (Bill Greiman)
 *   - RadioHead (Mike McCaulay)
 *
 * ── Câblage GPS ──────────────────────────────────────────────────────
 *   GPS TX  --> Arduino pin 2  (RX Arduino)
 *   GPS RX  --> Arduino pin 3  (TX Arduino)
 *   GPS VCC --> 3.3 V ou 5 V selon le module
 *   GPS GND --> GND
 *
 * ── Câblage module LoRa (interface UART) ─────────────────────────────
 *   LoRa TX --> Arduino pin 5  (RX Arduino)
 *   LoRa RX --> Arduino pin 6  (TX Arduino)
 *   LoRa VCC --> 3.3 V
 *   LoRa GND --> GND
 *
 * ── Câblage SD (SPI) ─────────────────────────────────────────────────
 *   SD CS   --> pin SS  (pin 10 sur Uno/Nano)
 *   SD MOSI --> pin 11
 *   SD MISO --> pin 12
 *   SD SCK  --> pin 13
 *
 * ── LED_BUILTIN (pin 13) ─────────────────────────────────────────────
 *   Clignote rapidement : initialisation en cours
 *   Clignote lentement  : enregistrement SD OK
 *   Allumée en continu  : erreur SD fatale
 */

#include <SPI.h>
#include <SoftwareSerial.h>
#include "SdFat.h"
#include <RH_RF95.h>

// ── Paramètres GPS ───────────────────────────────────────────────────
#define GPS_RX_PIN   2
#define GPS_TX_PIN   3
#define GPS_BAUD     9600

// ── Paramètres SD ────────────────────────────────────────────────────
#define SD_CS_PIN        SS
#define FILE_BASE_NAME   "GPS"   // max 6 caractères
#define NMEA_BUF_SIZE    96      // norme NMEA : max 82 car.
#define SYNC_EVERY_N     1       // sync SD à chaque trame

// ── Paramètres LoRa ──────────────────────────────────────────────────
#define LORA_RX_PIN      5
#define LORA_TX_PIN      6
#define LORA_BAUD        9600
#define LORA_FREQ        434.0   // MHz — adapter à votre région
// Intervalle minimum entre deux envois LoRa (ms).
// Duty cycle EU 434 MHz : 1 % → ~70 ms on = 7 s off minimum.
// On prend 10 s pour rester largement dans les limites.
#define LORA_INTERVAL_MS 10000UL

// ─────────────────────────────────────────────────────────────────────

SoftwareSerial gpsSerial (GPS_RX_PIN,  GPS_TX_PIN);
SoftwareSerial loraSerial(LORA_RX_PIN, LORA_TX_PIN);

SdFat  sd;
SdFile logFile;

RH_RF95<SoftwareSerial> rf95(loraSerial);

// ── Buffer NMEA ──────────────────────────────────────────────────────
char     nmeaBuf[NMEA_BUF_SIZE];
uint8_t  nmeaIdx    = 0;
bool     inSentence = false;
uint32_t frameCount = 0;

// ── État LoRa ────────────────────────────────────────────────────────
bool     loraOk      = false;
uint32_t lastLoraSend = 0;

#define sdError(msg) sd.errorHalt(F(msg))

// ─────────────────────────────────────────────────────────────────────
// Retourne vrai si la trame est une $GPRMC ou $GNRMC.
// Ces phrases contiennent : heure, validité, lat, lon, vitesse, cap.
// ─────────────────────────────────────────────────────────────────────
static bool isPositionSentence(const char* buf) {
    return (strncmp(buf, "$GPRMC", 6) == 0 ||
            strncmp(buf, "$GNRMC", 6) == 0);
}

// ─────────────────────────────────────────────────────────────────────
// Envoie `len` octets de `buf` via LoRa, avec rate limiting.
// Gère le listen() : GPS écoute par défaut, on bascule sur LoRa
// uniquement pendant l'envoi (~70–100 ms), puis on revient au GPS.
// ─────────────────────────────────────────────────────────────────────
static void sendLoRa(const char* buf, uint8_t len) {
    if (!loraOk) return;

    uint32_t now = millis();
    if (now - lastLoraSend < LORA_INTERVAL_MS) return;

    loraSerial.listen();
    rf95.send((const uint8_t*)buf, len);
    rf95.waitPacketSent();
    lastLoraSend = millis();

    // Retour immédiat sur le GPS pour ne pas manquer les trames suivantes
    gpsSerial.listen();
}

// ─────────────────────────────────────────────────────────────────────
void setup() {
    pinMode(LED_BUILTIN, OUTPUT);

    Serial.begin(9600);

    // Le GPS doit écouter en priorité
    gpsSerial.begin(GPS_BAUD);
    gpsSerial.listen();

    // Clignotement rapide pendant l'init
    for (uint8_t i = 0; i < 6; i++) {
        digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
        delay(150);
    }

    Serial.println(F("=== GPS Logger + LoRa ==="));

    // ── Init SD ──────────────────────────────────────────────────────
    if (!sd.begin(SD_CS_PIN, SD_SCK_MHZ(50))) {
        digitalWrite(LED_BUILTIN, HIGH);
        sd.initErrorHalt();
    }

    // Trouver un nom de fichier disponible : GPS00.txt → GPS99.txt
    const uint8_t BASE_LEN = sizeof(FILE_BASE_NAME) - 1;
    char fileName[13];
    memcpy(fileName, FILE_BASE_NAME, BASE_LEN);
    fileName[BASE_LEN]     = '0';
    fileName[BASE_LEN + 1] = '0';
    fileName[BASE_LEN + 2] = '.';
    fileName[BASE_LEN + 3] = 't';
    fileName[BASE_LEN + 4] = 'x';
    fileName[BASE_LEN + 5] = 't';
    fileName[BASE_LEN + 6] = '\0';

    while (sd.exists(fileName)) {
        if (fileName[BASE_LEN + 1] != '9') {
            fileName[BASE_LEN + 1]++;
        } else if (fileName[BASE_LEN] != '9') {
            fileName[BASE_LEN + 1] = '0';
            fileName[BASE_LEN]++;
        } else {
            digitalWrite(LED_BUILTIN, HIGH);
            sdError("Plus de noms de fichiers disponibles (GPS00-GPS99 existent)");
        }
    }

    if (!logFile.open(fileName, O_WRONLY | O_CREAT | O_EXCL)) {
        digitalWrite(LED_BUILTIN, HIGH);
        sdError("Impossible d'ouvrir le fichier");
    }

    Serial.print(F("Fichier SD : "));
    Serial.println(fileName);

    // ── Init LoRa ─────────────────────────────────────────────────────
    // On bascule sur loraSerial le temps de l'init, puis retour GPS.
    loraSerial.begin(LORA_BAUD);
    loraSerial.listen();

    if (rf95.init()) {
        rf95.setFrequency(LORA_FREQ);
        loraOk = true;
        Serial.print(F("LoRa OK @ "));
        Serial.print(LORA_FREQ);
        Serial.println(F(" MHz"));
    } else {
        Serial.println(F("LoRa ERREUR — mode SD seul"));
    }

    gpsSerial.listen();

    Serial.println(F("Enregistrement en cours..."));
}

// ─────────────────────────────────────────────────────────────────────
void loop() {
    while (gpsSerial.available()) {
        char c = (char)gpsSerial.read();

        // Écho USB pour surveillance
        Serial.write(c);

        // ── Accumulation de la trame NMEA ──
        if (c == '$') {
            nmeaIdx    = 0;
            inSentence = true;
        }

        if (inSentence) {
            if (nmeaIdx < NMEA_BUF_SIZE - 1) {
                nmeaBuf[nmeaIdx++] = c;
            } else {
                // Buffer plein sans '\n' : trame invalide
                inSentence = false;
                nmeaIdx    = 0;
            }

            if (c == '\n') {
                // ── Écriture SD (toutes les trames) ──
                logFile.write((uint8_t*)nmeaBuf, nmeaIdx);

                frameCount++;
                if (frameCount % SYNC_EVERY_N == 0) {
                    if (!logFile.sync()) {
                        digitalWrite(LED_BUILTIN, HIGH);
                        sdError("Erreur sync SD");
                    }
                    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
                }

                // ── Envoi LoRa (GPRMC/GNRMC uniquement, rate-limité) ──
                if (isPositionSentence(nmeaBuf)) {
                    sendLoRa(nmeaBuf, nmeaIdx);
                }

                inSentence = false;
                nmeaIdx    = 0;
            }
        }
    }
}
