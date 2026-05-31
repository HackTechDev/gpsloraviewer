# GPS LoRa Logger

Système de suivi GPS en deux parties :

- **`gps_lora_logger.ino`** — émetteur terrain : enregistre les trames NMEA sur carte SD et les transmet via LoRa en temps réel
- **`rf95_server/rf95_server.ino`** — récepteur base : reçoit les trames LoRa et les relaie vers le port Serial USB du PC

## Architecture

```
[Arduino Terrain]                    [Arduino Base]
  Module GPS (NMEA 1 Hz)               Serial USB → PC / GPS Viewer
       |                                      |
  gps_lora_logger.ino              rf95_server.ino
       |                                      |
  SD : GPS00.txt (toutes trames)    Affiche $GPRMC + RSSI
       |                                      |
  LoRa TX -------- 434 MHz ------> LoRa RX
    $GPRMC toutes les 10 s
```

---

## `gps_lora_logger.ino` — Émetteur terrain

- Lit les trames NMEA depuis un module GPS
- Enregistre **toutes** les trames sur carte SD (`GPS00.txt` → `GPS99.txt`)
- Transmet les trames `$GPRMC`/`$GNRMC` via LoRa toutes les 10 secondes
- Fonctionne en mode SD seul si le module LoRa est absent

## Bibliothèques requises

| Bibliothèque | Auteur | Installation |
|---|---|---|
| SdFat | Bill Greiman | Arduino Library Manager |
| RadioHead | Mike McCaulay | Arduino Library Manager |

## Câblage

### Module GPS

| GPS | Arduino |
|-----|---------|
| TX | Pin 2 (RX) |
| RX | Pin 3 (TX) |
| VCC | 3.3 V ou 5 V selon le module |
| GND | GND |

### Module LoRa (interface UART)

Module utilisé : [Grove LoRa 113060007](https://www.gotronic.fr/art-module-grove-lora-113060007-25947.htm)

| LoRa | Arduino |
|------|---------|
| TX | Pin 5 (RX) |
| RX | Pin 6 (TX) |
| VCC | 3.3 V |
| GND | GND |

### Carte SD (SPI)

| SD | Arduino Uno/Nano |
|----|-----------------|
| CS | Pin 10 (SS) |
| MOSI | Pin 11 |
| MISO | Pin 12 |
| SCK | Pin 13 |

## Paramètres configurables

Dans `gps_lora_logger.ino` :

| Constante | Valeur par défaut | Description |
|-----------|-------------------|-------------|
| `GPS_RX_PIN` | 2 | Pin RX du GPS |
| `GPS_TX_PIN` | 3 | Pin TX du GPS |
| `GPS_BAUD` | 9600 | Vitesse du GPS |
| `SD_CS_PIN` | SS (10) | Chip Select SD |
| `FILE_BASE_NAME` | `"GPS"` | Préfixe des fichiers SD |
| `SYNC_EVERY_N` | 1 | Sync SD toutes les N trames |
| `LORA_RX_PIN` | 5 | Pin RX du module LoRa |
| `LORA_TX_PIN` | 6 | Pin TX du module LoRa |
| `LORA_FREQ` | 434.0 | Fréquence LoRa (MHz) |
| `LORA_INTERVAL_MS` | 10000 | Intervalle minimum entre deux envois LoRa (ms) |

## LED de statut (pin 13)

| Comportement | Signification |
|---|---|
| Clignote rapidement | Initialisation en cours |
| Clignote lentement | Enregistrement SD OK |
| Allumée en continu | Erreur SD fatale |

## Notes

- **Duty cycle LoRa** : la fréquence 434 MHz est soumise à la règlementation EU (1 % duty cycle). L'intervalle de 10 s garantit le respect de cette limite pour des trames GPRMC de ~70 octets.
- **Deux SoftwareSerial sur AVR** : une seule instance peut écouter à la fois. Pendant l'envoi LoRa (~100 ms), les octets GPS entrants sont perdus. Cela est acceptable car le GPS émet à 1 Hz et les envois LoRa sont espacés de 10 s.
- **Dégradation gracieuse** : si le module LoRa ne répond pas au démarrage, le sketch continue en mode SD seul.

---

## `rf95_server.ino` — Récepteur base

À flasher sur un **Arduino dédié** (distinct de l'émetteur terrain). Reçoit les trames LoRa et les relaie vers le port Serial USB à 115200 baud.

### Câblage module LoRa (AVR Uno/Nano)

| LoRa | Arduino |
|------|---------|
| TX | Pin 10 (RX) |
| RX | Pin 11 (TX) |
| VCC | 3.3 V |
| GND | GND |

> Les pins 10 et 11 sont libres sur un Arduino dédié récepteur (pas de SD).

### Paramètre configurable

| Constante | Valeur | Description |
|-----------|--------|-------------|
| `LORA_FREQ` | 434.0 | Doit être identique à l'émetteur |

### Format de sortie Serial USB (115200 baud)

```
# GPS LoRa Receiver — en attente de trames...
# LoRa OK @ 434.00 MHz
$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A
# [1] RSSI: -67 dBm
$GPRMC,123529,A,4807.045,N,01131.012,E,021.9,084.4,230394,003.1,W*6B
# [2] RSSI: -68 dBm
```

Les lignes `#` sont des diagnostics ; un parseur NMEA standard les ignore.

### LED de statut (pin 13)

| Comportement | Signification |
|---|---|
| Flash 50 ms | Trame NMEA reçue et relayée |

---

## Contenu du dossier

```
gps_lora_logger/
├── gps_lora_logger.ino        # Émetteur terrain (SD + LoRa TX)
├── rf95_client/
│   └── rf95_client.ino        # Sketch client LoRa de référence (RadioHead)
└── rf95_server/
    └── rf95_server.ino        # Récepteur base (LoRa RX → Serial USB)
```
