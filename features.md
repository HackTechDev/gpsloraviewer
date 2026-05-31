# Fonctionnalités — GPS Viewer

## Fichier de trace JSON

Le fichier de trace JSON est le document central de l'application. Il regroupe :
- les chemins absolus vers une ou plusieurs traces GPS NMEA
- toutes les annotations photo (position, miniature, titre, description, angle de vue)

**Opérations disponibles (menu Fichier) :**

| Action | Raccourci | Description |
|--------|-----------|-------------|
| Nouveau parcours… | Ctrl+N | Crée un nouveau fichier JSON vide (réinitialise la session) |
| Ouvrir… | — | Charge un fichier JSON existant (traces GPS + photos) |
| Ajouter une trace GPS… | Ctrl+O | Ajoute une trace NMEA sur la carte courante |
| Enregistrer | Ctrl+S | Sauvegarde dans le fichier actif |
| Enregistrer sous… | Ctrl+Shift+S | Sauvegarde sous un nouveau nom |
| Propriétés du parcours… | Ctrl+I | Modifier le titre et la description du parcours |

- Au **démarrage**, un écran de démarrage (splash screen) s'affiche brièvement pendant le chargement. Un fichier `logo.png` à la racine du projet personnalise le logo.
- Au **démarrage** sans argument, le dernier fichier JSON utilisé est rouvert automatiquement (`~/.config/gps_viewer/last_track.txt`)
- **Fichiers récents JSON** : menu Fichier → Fichiers récents JSON (10 derniers, persistés dans `~/.config/gps_viewer/recent_tracks.json`)
- **Glisser-déposer** d'un fichier `.txt` / `.nmea` / `.log` directement sur la fenêtre
- **Argument en ligne de commande** : `python3 gps_viewer.py fichier.txt`
- La barre de titre indique : `GPS Viewer  [nom.json] — fichier.txt`

### Format JSON

```json
{
  "gps_files": ["/chemin/absolu/GPS01.txt", "/chemin/absolu/GPS02.txt"],
  "photos": [
    {
      "lat": 48.123456, "lon": 7.654321,
      "file": "tracks/images/photo_20250101_001.jpg",
      "thumb": "tracks/images/photo_20250101_001_thumb.jpg",
      "titre": "Titre optionnel",
      "description": "Description optionnelle",
      "angle": 90.0
    }
  ]
}
```

## Traces GPS

- **Plusieurs traces simultanées** : chaque fichier NMEA ajouté est affiché avec une couleur distincte (palette de 8 couleurs cycliques)
- Filtrage automatique des trames invalides (`fix_quality = 0`)
- Chaque trace affiche un marqueur de **départ** (cercle) et d'**arrivée** (carré) dans sa couleur
- La légende indique le nom de chaque fichier
- **Sélecteur de trace** : dès que deux traces ou plus sont chargées, un sélecteur `📊 Graphiques :` apparaît dans la barre d'outils pour choisir quelle trace est analysée dans les graphiques, les statistiques et le curseur carte

## Carte

- Affichage des traces GPS sur une carte interactive rendue nativement (matplotlib + contextily)
- **Zoom à la molette** centré sur le pointeur
- **Pan** par clic gauche + glisser
- **Recentrage** sur toutes les traces : bouton `⌂ Recentrer` (Ctrl+R)

### Fonds de carte disponibles

| Source | Description |
|--------|-------------|
| OpenStreetMap | Carte standard (défaut) |
| Satellite Esri | Vue satellite mondiale |
| Orthophoto IGN | Photographies aériennes IGN France |
| Plan IGN | Cartographie topographique IGN France |

Changement via le bouton `🗺 Fond de carte` dans la barre d'outils.

### Coloration de la trace

Sélectionnable via le bouton `🎨 Trace` :

| Mode | Description |
|------|-------------|
| Couleur unie | Couleur de palette par trace (défaut) |
| Altitude | Gradient bleu → vert → jaune → rouge selon l'altitude |
| Vitesse | Gradient vert → orange → rouge selon la vitesse instantanée |

Une colorbar est affichée en incrustation pour les modes dégradés.

### Outils cartographiques

- **Grille de coordonnées** (Ctrl+L) : quadrillage lat/lon adaptatif avec étiquettes, recalculé à chaque zoom/pan
- **Miniature de localisation** (Ctrl+M) : inset en bas à droite affichant la trace complète et un rectangle rouge indiquant la vue courante
- **Mesure de distance** (Ctrl+D) : outil clic-à-clic en mode croix
  - Chaque clic pose un point et affiche le segment ainsi que le cumul total
  - Ligne rubber-band animée avec la distance live entre deux clics
  - Double-clic pour figer la mesure (les segments restent affichés) et démarrer une nouvelle
  - Plusieurs mesures simultanées possibles ; Échap pour tout effacer
  - Distances affichées en mètres (< 1 km) ou kilomètres (3 décimales)

## Annotations photo

- **Mode photo** : bouton `📷 Photo` ou touche `P` — le curseur devient une croix
- Clic sur la carte → sélecteur de fichier image (JPG, PNG, BMP, GIF, TIFF, WebP)
- L'image originale est copiée dans `tracks/images/`, une miniature 80×80 px est générée
- Chaque annotation affiche une croix rouge et la miniature reliée par une flèche
- **Clic sur la croix ou la miniature** → visionneuse plein format avec :
  - Affichage de l'image (jusqu'à 90 % de l'écran)
  - Coordonnées GPS et chemin du fichier
  - Champs titre et description éditables
  - Bouton Supprimer (supprime les fichiers + l'entrée JSON)
- **Indicateur de direction** (œil) : survoler une annotation puis :
  - `V` — affiche / masque l'indicateur
  - `W` — tourne de +15°
  - `X` — tourne de −15°
- Les annotations et leurs paramètres sont sauvegardés dans le fichier JSON actif

## Graphiques

- **Profil altimétrique** : altitude en mètres en fonction de la distance parcourue
- **Profil de vitesse** : vitesse en km/h calculée par différentiel Haversine entre trames successives, lissée sur 5 points
- Curseur rouge synchronisé : survoler un graphique déplace le repère sur la carte et réciproquement

## Panneau de statistiques

Affiché en permanence à droite de la carte :

| Statistique | Description |
|-------------|-------------|
| Fichier | Nom du fichier GPS actif |
| Points GPS | Nombre de positions valides |
| Distance | Distance totale parcourue (mètres) |
| Durée | Durée de l'enregistrement (h/min/s) |
| Altitude min / max / moyenne | En mètres |
| Vitesse max / moyenne | En km/h |

**Bloc curseur** : au survol d'un graphique, affiche en temps réel l'heure, la latitude, la longitude, l'altitude, la vitesse, la distance et le nombre de satellites pour le point courant.

## Navigation par coordonnées

- Menu **Navigation → Aller aux coordonnées…** (Ctrl+G) ou bouton `📍 Coordonnées`
- Saisie de la latitude et longitude avec 6 décimales
- Champ de collage rapide : coller `48.8566, 2.3522` remplit automatiquement les champs
- Sélecteur de niveau de zoom (1 à 19)
- Un repère rouge est affiché à la position choisie
- Zoom, pan et changement de couche restent fonctionnels après navigation

## Vue 3D (Ctrl+3)

Fenêtre indépendante (non bloquante) affichant toutes les traces GPS chargées en trois dimensions.

- Axes **Est / Nord** en mètres (coordonnées Web Mercator centrées sur le centroïde), axe **Altitude** en mètres
- Marqueurs départ (●) et arrivée (■) pour chaque trace
- Trois **modes de coloration** :

| Mode | Description |
|------|-------------|
| Couleur unie | Couleur fixe par trace (palette cyclique) |
| 🏔 Altitude | Gradient de couleur selon l'altitude (colorbar affichée) |
| ⚡ Vitesse | Gradient de couleur selon la vitesse (colorbar affichée) |

- **Fond de carte OSM** : tuiles OpenStreetMap affichées comme plan horizontal à la base de la scène, téléchargées en arrière-plan (`QThread`) sans bloquer l'interface
  - Bouton toggle `🗺 Fond OSM` pour afficher / masquer
  - **Sélecteur de résolution** : Basse (64 px / 4 096 polygones), Moyenne (128 px), Haute (256 px) — le changement de résolution est instantané (rééchantillonnage depuis l'image brute mise en cache, sans re-téléchargement)
  - La surface OSM est automatiquement masquée pendant la rotation pour garantir la fluidité, et réaffichée au relâchement
- **Rotation fluide** : la caméra ne peut pas passer sous le plan horizontal (élévation clampée à ≥ 0°)
- Bouton `⌂ Réinitialiser la vue` pour revenir à l'angle par défaut (élev 25°, azim −60°)
- La fenêtre se met à jour automatiquement lors de l'ajout d'une nouvelle trace

## Performances

- **Chargement asynchrone des tuiles** : téléchargement en arrière-plan via `QThread` ; les traces sont immédiatement visibles pendant que les tuiles se chargent
- **Barre de progression** : indicateur pulsé dans la barre de statut pendant le téléchargement
- **Cache LRU en mémoire** : 20 dernières vues conservées en RAM pour des aller-retours instantanés
- **Cache persistant de tuiles** : `~/.cache/gps_viewer/tiles/` réutilisé entre les sessions
- **Zoom adaptatif** : niveau de zoom OSM calculé automatiquement depuis l'étendue de la vue courante
- **Simplification Douglas-Peucker** : epsilon ≈ 1,5 pixel, recalculé à chaque zoom/pan ; activé pour les traces ≥ 500 points

## Cache de tuiles

- Tuiles stockées dans `~/.cache/gps_viewer/tiles/` entre les sessions
- **Outils → Informations sur le cache** : chemin, taille (Mo), nombre de fichiers
- **Outils → Vider le cache** : suppression avec confirmation et affichage de la taille libérée

## Visualisation HTML (gps_map.py)

- Génère une page HTML autonome avec Folium (Leaflet.js)
- Trace GPS colorée sur OpenStreetMap
- Deux graphiques Chart.js côte à côte : altitude (bleu) et vitesse (vert)
- Curseur synchronisé entre la carte et les graphiques au survol
- Panneau d'informations résumant les statistiques du parcours

## Système d'acquisition Arduino (`gps_lora_logger/`)

### Émetteur terrain (`gps_lora_logger.ino`)

- Lecture des trames NMEA via SoftwareSerial (pins 2/3, 9600 baud)
- Enregistrement de **toutes** les trames sur carte SD via SdFat (CS = pin SS)
- Nommage automatique des fichiers : `GPS00.txt` → `GPS99.txt`
- Synchronisation SD à chaque trame pour éviter les pertes en cas de coupure
- **Transmission LoRa** : envoi des trames `$GPRMC`/`$GNRMC` via RadioHead RH_RF95 (SoftwareSerial pins 5/6, 434 MHz)
  - Rate limiting 10 s entre deux envois (conformité duty cycle EU 1 %)
  - Filtrage : seules les trames de position sont transmises, toutes sont écrites sur SD
  - Dégradation gracieuse : si le module LoRa est absent, l'enregistrement SD continue normalement
- Indicateur LED : clignotement rapide (init), lent (enregistrement OK), fixe (erreur SD)
- Écho des trames sur le port série USB pour surveillance en temps réel

### Récepteur base (`rf95_server/rf95_server.ino`)

- À flasher sur un **Arduino dédié** (distinct de l'émetteur terrain)
- Reçoit les trames LoRa et les relaie vers le port Serial USB (115200 baud)
- Validation minimale : seuls les paquets commençant par `$` sont relayés
- Affiche le RSSI et un compteur de paquets sur des lignes `#` (ignorées par les parseurs NMEA)
- Compatible multi-plateformes : AVR, RP2040, ESP32, SAMD, STM32, nRF52840
- Indicateur LED : flash 50 ms à chaque trame reçue
