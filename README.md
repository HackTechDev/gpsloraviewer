# GPS LoRa

Système complet de suivi GPS : acquisition sur le terrain via Arduino, transmission LoRa en temps réel, et visualisation desktop PyQt5.

## Architecture du projet

```
gpslora/
├── gps_viewer/                    # Application desktop PyQt5
│   ├── gps_viewer.py              #   Point d'entrée principal
│   ├── gps_nmea.py                #   Parseur NMEA
│   ├── map_canvas.py              #   Widget carte (matplotlib + contextily)
│   ├── chart_canvas.py            #   Widget graphiques
│   ├── stats_panel.py             #   Panneau de statistiques
│   ├── dialogs.py                 #   Boîtes de dialogue
│   ├── view_3d.py                 #   Vue 3D (matplotlib 3D + OSM)
│   ├── gps_map.py                 #   Générateur carte HTML (Folium)
│   └── tracks/                    #   Données utilisateur (non versionnées)
│       ├── gps/                   #     Traces NMEA brutes (GPS00.txt…)
│       ├── images/                #     Photos annotées + miniatures
│       └── *.json                 #     Fichiers de parcours
├── gps_lora_logger/               # Firmware Arduino
│   ├── gps_lora_logger.ino        #   Émetteur terrain (SD + LoRa TX)
│   ├── rf95_server/
│   │   └── rf95_server.ino        #   Récepteur base (LoRa RX → Serial USB)
│   └── rf95_client/
│       └── rf95_client.ino        #   Client LoRa de référence (RadioHead)
├── exemples/                      # Exemples de sketches Arduino
├── runGPSLoRa.sh                  # Lanceur (Linux/macOS)
├── features.md                    # Description détaillée des fonctionnalités
├── improvements.md                # Pistes d'amélioration
└── user_guide.md                  # Guide utilisateur
```

## Démarrage rapide

### Lancer l'application

```bash
./runGPSLoRa.sh
# ou
python3 gps_viewer/gps_viewer.py
# ou avec un fichier JSON directement :
python3 gps_viewer/gps_viewer.py session.json
```

### Dépendances Python

```bash
pip install PyQt5 matplotlib contextily numpy Pillow folium
```

---

## Système d'acquisition Arduino (`gps_lora_logger/`)

### Émetteur terrain — `gps_lora_logger.ino`

À flasher sur l'**Arduino terrain** (avec GPS + SD + module LoRa).

| Composant | Connexion |
|-----------|-----------|
| GPS TX | Pin 2 (RX) |
| GPS RX | Pin 3 (TX) |
| LoRa TX | Pin 5 (RX) |
| LoRa RX | Pin 6 (TX) |
| SD CS | Pin 10 (SS) |
| SD MOSI/MISO/SCK | Pins 11 / 12 / 13 |

**Bibliothèques :** SdFat (Bill Greiman), RadioHead — version patchée fournie dans `gps_lora_logger/lib/Grove_LoRa_Radio/`

> **Installation de la bibliothèque RadioHead patchée**
>
> La version originale de la bibliothèque Grove LoRa (`Grove_-_LoRa_Radio_433MHz_868MHz`) ne compile pas sur AVR (Uno/Nano) en raison d'une incompatibilité de `stdatomic.h` avec avr-g++. Une version corrigée est incluse dans ce dépôt.
>
> Copier le dossier dans le répertoire des bibliothèques Arduino :
> ```bash
> cp -r gps_lora_logger/lib/Grove_LoRa_Radio \
>       ~/Arduino/libraries/Grove_-_LoRa_Radio_433MHz_868MHz
> ```
> **Correctif appliqué** (`RadioHead.h`, ligne ~818) : ajout d'une garde `#elif defined(__AVR__)` pour utiliser `<util/atomic.h>` (avr-libc) au lieu de `<stdatomic.h>` (C11, non supporté par avr-g++ en mode C++).

- Enregistre **toutes** les trames NMEA sur SD (`GPS00.txt` → `GPS99.txt`)
- Transmet les trames `$GPRMC` via LoRa toutes les **10 s** — SF7 (défaut RadioHead), airtime ~70 ms, duty cycle EU433 < 1 %
- Fonctionne en mode SD seul si le module LoRa est absent

**LED (pin 13) :** clignote rapidement (init) · lentement (OK) · fixe (erreur SD)

### Récepteur base — `rf95_server/rf95_server.ino`

À flasher sur un **Arduino dédié** connecté au PC.

| Composant | Connexion (AVR) |
|-----------|-----------------|
| LoRa TX | Pin 10 (RX) |
| LoRa RX | Pin 11 (TX) |

- Reçoit les trames LoRa et les relaie vers le port Serial USB (115 200 baud)
- Affiche le RSSI sur des lignes `#` (ignorées par les parseurs NMEA)

**LED (pin 13) :** flash 50 ms à chaque trame reçue

---

## Application desktop (`gps_viewer/`)

### Carte interactive

- Traces GPS multi-fichiers sur fond de carte (OpenStreetMap, Satellite Esri, IGN)
- Zoom molette, pan, recentrage `⌂` (Ctrl+R)
- Coloration de la trace : couleur unie / altitude / vitesse (gradients + colorbar)
- Grille de coordonnées (Ctrl+L), miniature de localisation (Ctrl+M)
- Outil de mesure de distance clic-à-clic (Ctrl+D)

### Vue 3D (Ctrl+3)

- Traces GPS en 3D (axes Est / Nord / Altitude)
- Fond de carte OSM comme plan horizontal (téléchargement asynchrone)
- Sélecteur de résolution : Basse (64 px) / Moyenne (128 px) / Haute (256 px)
- Caméra bloquée au-dessus du plan horizontal

### Annotations photo

- Clic sur la carte → ajout d'une photo géolocalisée avec miniature, titre, description
- Visionneuse plein format, indicateur de direction orientable

### Graphiques et statistiques

- Profil altimétrique et profil de vitesse synchronisés avec la carte
- Panneau de statistiques : distance, durée, altitude, vitesse
- Bloc curseur temps réel au survol des graphiques

### Fichier de trace JSON

```json
{
  "gps_files": ["/chemin/absolu/gps_viewer/tracks/gps/GPS01.txt"],
  "photos": [
    {
      "lat": 48.123456, "lon": 7.654321,
      "file": "/chemin/absolu/gps_viewer/tracks/images/photo_001.jpg",
      "thumb": "/chemin/absolu/gps_viewer/tracks/images/photo_001_thumb.jpg",
      "titre": "Titre", "description": "...", "angle": 90.0
    }
  ]
}
```

### Raccourcis clavier

| Raccourci | Action |
|-----------|--------|
| Ctrl+N | Nouveau parcours |
| Ctrl+O | Ajouter une trace GPS |
| Ctrl+S | Enregistrer |
| Ctrl+Shift+S | Enregistrer sous… |
| Ctrl+I | Propriétés du parcours |
| Ctrl+R | Recentrer sur la trace |
| Ctrl+L | Grille de coordonnées |
| Ctrl+M | Miniature de localisation |
| Ctrl+D | Outil de mesure |
| Ctrl+G | Naviguer vers des coordonnées |
| Ctrl+3 | Vue 3D |
| P | Mode annotation photo |
| Échap | Effacer les mesures |

### Fichiers de configuration

| Fichier | Contenu |
|---------|---------|
| `~/.config/gps_viewer/last_track.txt` | Dernier fichier JSON ouvert |
| `~/.config/gps_viewer/recent_tracks.json` | 10 derniers fichiers JSON |
| `~/.cache/gps_viewer/tiles/` | Cache persistant des tuiles |

### Visualisation HTML

```bash
python3 gps_viewer/gps_map.py gps_viewer/tracks/gps/GPS02.txt
# Génère GPS02_map.html et l'ouvre dans le navigateur
```
