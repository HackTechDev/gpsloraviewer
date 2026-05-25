/*
 * GPS Data Logger
 *
 * Lit les trames NMEA depuis un module GPS (SoftwareSerial pins 2/3)
 * et les enregistre sur carte SD (SPI, CS = pin SS).
 *
 * Bibliothèques requises : SdFat (Bill Greiman)
 *
 * Câblage GPS :
 *   GPS TX  --> Arduino pin 2
 *   GPS RX  --> Arduino pin 3
 *   GPS VCC --> 3.3V ou 5V selon le module
 *   GPS GND --> GND
 *
 * LED_BUILTIN (pin 13) :
 *   - Clignote rapidement  : initialisation SD en cours
 *   - Clignote lentement   : enregistrement OK
 *   - Allumée en continu   : erreur SD
 */

#include <SPI.h>
#include <SoftwareSerial.h>
#include "SdFat.h"

// ── Paramètres GPS ──────────────────────────────────────────────────
#define GPS_RX_PIN   2
#define GPS_TX_PIN   3
#define GPS_BAUD     9600

// ── Paramètres SD ───────────────────────────────────────────────────
#define SD_CS_PIN        SS
#define FILE_BASE_NAME   "GPS"   // max 6 caractères

// ── Taille du buffer pour une trame NMEA ────────────────────────────
// Une trame NMEA ne dépasse pas 82 caractères selon la norme.
#define NMEA_BUF_SIZE  96

// ── Fréquence de sync SD (en nombre de trames) ──────────────────────
// Sync à chaque trame pour ne rien perdre en cas de coupure.
#define SYNC_EVERY_N   1

// ────────────────────────────────────────────────────────────────────

SoftwareSerial gpsSerial(GPS_RX_PIN, GPS_TX_PIN);

SdFat  sd;
SdFile logFile;

char    nmeaBuf[NMEA_BUF_SIZE];
uint8_t nmeaIdx    = 0;
bool    inSentence = false;
uint32_t frameCount = 0;

#define sdError(msg) sd.errorHalt(F(msg))

// ────────────────────────────────────────────────────────────────────
void setup() {
    pinMode(LED_BUILTIN, OUTPUT);

    Serial.begin(9600);
    gpsSerial.begin(GPS_BAUD);

    // Clignotement rapide pendant l'init
    for (uint8_t i = 0; i < 6; i++) {
        digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
        delay(150);
    }

    Serial.println(F("=== GPS Data Logger ==="));

    // ── Init SD ──
    if (!sd.begin(SD_CS_PIN, SD_SCK_MHZ(50))) {
        digitalWrite(LED_BUILTIN, HIGH);   // LED fixe = erreur
        sd.initErrorHalt();
    }

    // ── Trouver un nom de fichier disponible ──
    const uint8_t BASE_LEN = sizeof(FILE_BASE_NAME) - 1;  // sans '\0'
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
            sdError("Plus de noms de fichiers disponibles (GPS00-GPS99 existent deja)");
        }
    }

    if (!logFile.open(fileName, O_WRONLY | O_CREAT | O_EXCL)) {
        digitalWrite(LED_BUILTIN, HIGH);
        sdError("Impossible d'ouvrir le fichier");
    }

    Serial.print(F("Fichier : "));
    Serial.println(fileName);
    Serial.println(F("Enregistrement en cours..."));
}

// ────────────────────────────────────────────────────────────────────
void loop() {
    while (gpsSerial.available()) {
        char c = (char)gpsSerial.read();

        // ── Écho sur le port série pour surveillance ──
        Serial.write(c);

        // ── Accumulation de la trame NMEA ──
        if (c == '$') {
            // Début d'une nouvelle trame
            nmeaIdx    = 0;
            inSentence = true;
        }

        if (inSentence) {
            if (nmeaIdx < NMEA_BUF_SIZE - 1) {
                nmeaBuf[nmeaIdx++] = c;
            } else {
                // Buffer plein sans '\n' : trame invalide, on réinitialise
                inSentence = false;
                nmeaIdx    = 0;
            }

            if (c == '\n') {
                // Trame complète reçue : on l'écrit sur la SD
                logFile.write((uint8_t*)nmeaBuf, nmeaIdx);

                frameCount++;
                if (frameCount % SYNC_EVERY_N == 0) {
                    if (!logFile.sync()) {
                        digitalWrite(LED_BUILTIN, HIGH);
                        sdError("Erreur sync SD");
                    }
                    // Clignotement lent : enregistrement OK
                    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
                }

                inSentence = false;
                nmeaIdx    = 0;
            }
        }
    }
}
