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
├── exemples/                # Exemples de traces GPS
└── tracks/
    └── images/              # Miniatures et copies des photos annotées
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
# ou avec un fichier JSON directement :
python3 gps_viewer.py session.json
```

Au démarrage sans argument, le dernier fichier JSON utilisé est rouvert automatiquement.

### Visualisation HTML

```bash
python3 gps_map.py GPS02.txt
# Ouvre GPS02_map.html dans le navigateur par défaut
```

## Fichier de trace JSON

Le fichier `.json` est le document central de l'application. Il regroupe les chemins vers une ou plusieurs traces GPS NMEA et toutes les annotations photo.

```json
{
  "gps_files": ["/chemin/absolu/GPS01.txt", "/chemin/absolu/GPS02.txt"],
  "photos": [
    {
      "lat": 48.123456, "lon": 7.654321,
      "file": "tracks/images/photo_001.jpg",
      "thumb": "tracks/images/photo_001_thumb.jpg",
      "titre": "Titre optionnel",
      "description": "Description optionnelle",
      "angle": 90.0
    }
  ]
}
```

**Opérations disponibles (menu Fichier) :**

| Action | Raccourci | Description |
|--------|-----------|-------------|
| Ouvrir… | — | Charge un fichier JSON existant |
| Ajouter une trace GPS… | Ctrl+O | Ajoute une trace NMEA sur la carte courante |
| Enregistrer | Ctrl+S | Sauvegarde dans le fichier actif |
| Enregistrer sous… | Ctrl+Shift+S | Sauvegarde sous un nouveau nom |
| Fichiers récents JSON | — | 10 derniers fichiers JSON utilisés |

La barre de titre affiche : `GPS Viewer  [nom.json] — fichier.txt` (ou `— N traces GPS` si plusieurs).

## Fonctionnalités principales

### Traces GPS multiples

- **Plusieurs traces simultanées** : chaque fichier NMEA est affiché avec une couleur distincte (palette de 8 couleurs cycliques)
- Filtrage automatique des trames invalides (`fix_quality = 0`)
- Chaque trace affiche un marqueur de départ (cercle) et d'arrivée (carré) dans sa couleur
- Légende avec le nom de chaque fichier
- Les graphiques et statistiques reflètent la dernière trace ajoutée

### Carte interactive

- Trace GPS sur fond de carte rendu nativement (matplotlib + contextily)
- Zoom à la molette, pan par clic-glisser, recentrage `⌂` (Ctrl+R)

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
| Couleur unie | Couleur de palette par trace (défaut) |
| Altitude | Gradient bleu → vert → jaune → rouge |
| Vitesse | Gradient vert → orange → rouge |

### Outils cartographiques

- **Grille de coordonnées** (Ctrl+L) : quadrillage lat/lon adaptatif avec étiquettes
- **Miniature de localisation** (Ctrl+M) : vue d'ensemble avec rectangle de position courante
- **Mesure de distance** (Ctrl+D) : outil clic-à-clic
  - Ligne rubber-band animée entre deux clics avec distance live
  - Double-clic pour figer la mesure et démarrer une nouvelle
  - Plusieurs mesures simultanées ; Échap pour tout effacer

### Annotations photo

- **Mode photo** : bouton `📷 Photo` ou touche `P` — curseur croix
- Clic sur la carte → sélecteur de fichier image (JPG, PNG, BMP, GIF, TIFF, WebP)
- L'image est copiée dans `tracks/images/`, une miniature 80×80 px est générée
- Chaque annotation affiche une croix rouge et la miniature reliée par une flèche
- **Clic sur la croix ou la miniature** → visionneuse plein format avec titre, description éditables et bouton Supprimer
- **Indicateur de direction** (œil) : survoler une annotation puis `V` (afficher/masquer), `W` (+15°), `X` (−15°)

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
| Ctrl+O | Ajouter une trace GPS |
| Ctrl+S | Enregistrer le fichier JSON |
| Ctrl+Shift+S | Enregistrer sous… |
| Ctrl+R | Recentrer sur la trace |
| Ctrl+L | Afficher/masquer la grille de coordonnées |
| Ctrl+M | Afficher/masquer la miniature |
| Ctrl+D | Activer/désactiver l'outil de mesure |
| Ctrl+G | Naviguer vers des coordonnées |
| P | Activer/désactiver le mode photo |
| V | Afficher/masquer l'indicateur de direction (œil) |
| W | Tourner l'indicateur de +15° |
| X | Tourner l'indicateur de −15° |
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

## Fichiers de configuration

| Fichier | Contenu |
|---------|---------|
| `~/.config/gps_viewer/last_track.txt` | Chemin du dernier fichier JSON ouvert |
| `~/.config/gps_viewer/recent_tracks.json` | Liste des 10 derniers fichiers JSON |
| `~/.cache/gps_viewer/tiles/` | Cache persistant des tuiles cartographiques |

## Format de fichier GPS

Les fichiers `.txt` contiennent des trames NMEA brutes, notamment les trames `$GPGGA` :

```
$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47
```

Seules les trames `$GPGGA` avec `fix_quality > 0` sont utilisées.
