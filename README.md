# GPS Viewer

Application desktop de visualisation de traces GPS enregistrées depuis un module GPS via Arduino.

## Architecture du projet

```
gpslora/
├── gps_datalogger/
│   └── gps_datalogger.ino   # Sketch Arduino : lecture GPS + enregistrement SD
├── gps_viewer.py            # Application desktop PyQt5 (carte + graphiques)
├── gps_map.py               # Générateur de carte HTML (Folium + Chart.js)
├── GPS02.txt                # Exemple de fichier NMEA enregistré
└── exemples/                # Exemples de traces GPS
```

## Matériel requis (Arduino)

| Composant | Connexion |
|-----------|-----------|
| Module GPS | TX → pin 2, RX → pin 3, VCC → 3.3 V/5 V, GND → GND |
| Carte SD (SPI) | CS → pin SS (10), MOSI → 11, MISO → 12, SCK → 13 |
| LED | Pin 13 (LED_BUILTIN) — indicateur d'état |

**Bibliothèque Arduino requise :** SdFat (Bill Greiman)

### Comportement de la LED

| Signal | Signification |
|--------|---------------|
| Clignotement rapide | Initialisation SD en cours |
| Clignotement lent | Enregistrement en cours (OK) |
| Allumée fixe | Erreur SD |

Les fichiers sont créés automatiquement sous la forme `GPS00.txt` à `GPS99.txt`.

## Installation Python

```bash
pip install PyQt5 matplotlib contextily numpy
```

## Utilisation

### Enregistrement (Arduino)

1. Téléverser `gps_datalogger.ino` sur l'Arduino
2. Insérer la carte SD
3. Connecter le module GPS
4. L'enregistrement démarre automatiquement

### Visualisation desktop

```bash
python3 gps_viewer.py
# ou avec un fichier directement :
python3 gps_viewer.py GPS02.txt
```

### Visualisation HTML

```bash
python3 gps_map.py GPS02.txt
# Ouvre GPS02_map.html dans le navigateur par défaut
```

## Format de fichier GPS

Les fichiers `.txt` contiennent des trames NMEA brutes, notamment les trames `$GPGGA` :

```
$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47
```

Seules les trames `$GPGGA` avec `fix_quality > 0` sont utilisées.

## Cache de tuiles

Les tuiles cartographiques sont mises en cache dans `~/.cache/gps_viewer/tiles/` pour éviter de les re-télécharger. Le cache est géré via **Outils → Informations sur le cache** et **Outils → Vider le cache**.
