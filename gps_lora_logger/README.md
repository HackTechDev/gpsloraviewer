# GPS Lora Logger

Enregistreur GPS autonome sur carte SD avec transmission LoRa en temps réel.

- Lit les trames NMEA depuis un module GPS
- Enregistre **toutes** les trames sur carte SD (fichiers `GPS00.txt` → `GPS99.txt`)
- Transmet les trames de position (`$GPRMC`) via LoRa toutes les 10 secondes
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

## Contenu du dossier

```
gps_lora_logger/
├── gps_lora_logger.ino   # Sketch principal (SD + LoRa)
└── rf95_client/
    └── rf95_client.ino   # Sketch client LoRa de référence (RadioHead)
```
