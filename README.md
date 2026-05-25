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

## Fonctionnalités principales

### Chargement des données

- Ouverture via menu, bouton, glisser-déposer ou argument en ligne de commande
- **Fichiers récents** : 10 derniers fichiers accessibles via Fichier → Fichiers récents
- Filtrage automatique des trames invalides

### Carte interactive

- Trace GPS sur fond de carte rendu nativement (matplotlib + contextily)
- Zoom à la molette, pan par clic-glisser, recentrage `⌂` (Ctrl+R)
- Marqueur de départ (cercle vert) et d'arrivée (carré rouge)

**Fonds de carte disponibles :**

| Source | Description |
|--------|-------------|
| OpenStreetMap | Carte standard (défaut) |
| Satellite Esri | Vue satellite mondiale |
| Orthophoto IGN | Photographies aériennes IGN France |
| Plan IGN | Cartographie topographique IGN France |

**Coloration de la trace :**

| Mode | Description |
|------|-------------|
| Couleur unie | Bleu uni (défaut) |
| Altitude | Gradient bleu → vert → jaune → rouge |
| Vitesse | Gradient vert → orange → rouge |

### Outils cartographiques

- **Grille de coordonnées** (Ctrl+L) : quadrillage lat/lon adaptatif avec étiquettes
- **Miniature de localisation** (Ctrl+M) : vue d'ensemble avec rectangle de position courante
- **Mesure de distance** (Ctrl+D) : outil clic-à-clic
  - Ligne rubber-band animée entre deux clics avec distance live
  - Double-clic pour figer la mesure et démarrer une nouvelle
  - Plusieurs mesures simultanées ; Échap pour tout effacer

### Navigation par coordonnées

- Menu Navigation → Aller aux coordonnées… (Ctrl+G) ou bouton `📍 Coordonnées`
- Saisie latitude/longitude, sélecteur de niveau de zoom, repère rouge affiché

### Graphiques synchronisés

- Profil altimétrique (altitude vs distance)
- Profil de vitesse (km/h, lissé sur 5 points)
- Curseur rouge synchronisé entre la carte et les graphiques

### Panneau de statistiques

Distance totale, durée, altitude min/max/moy, vitesse max/moy. Bloc curseur en temps réel au survol des graphiques.

## Raccourcis clavier

| Raccourci | Action |
|-----------|--------|
| Ctrl+O | Ouvrir un fichier |
| Ctrl+R | Recentrer sur la trace |
| Ctrl+L | Afficher/masquer la grille de coordonnées |
| Ctrl+M | Afficher/masquer la miniature |
| Ctrl+D | Activer/désactiver l'outil de mesure |
| Ctrl+G | Naviguer vers des coordonnées |
| Échap | Effacer toutes les mesures |

## Performances

- Chargement asynchrone des tuiles (QThread) — la trace est visible immédiatement
- Barre de progression pulsée pendant le téléchargement
- Cache LRU en mémoire (20 vues) pour des aller-retours instantanés
- Zoom adaptatif : niveau OSM calculé depuis l'étendue de la vue
- Simplification Douglas-Peucker (ε ≈ 1,5 px) pour les traces ≥ 500 points

## Cache de tuiles

Les tuiles sont stockées dans `~/.cache/gps_viewer/tiles/` entre les sessions.

- **Outils → Informations sur le cache** : chemin, taille (Mo), nombre de fichiers
- **Outils → Vider le cache** : suppression avec confirmation

## Format de fichier GPS

Les fichiers `.txt` contiennent des trames NMEA brutes, notamment les trames `$GPGGA` :

```
$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47
```

Seules les trames `$GPGGA` avec `fix_quality > 0` sont utilisées.
