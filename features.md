# Fonctionnalités — GPS Viewer

## Chargement des données

- **Ouverture de fichier** via le menu Fichier → Ouvrir ou le bouton `📂 Ouvrir` (Ctrl+O)
- **Glisser-déposer** d'un fichier `.txt` / `.nmea` / `.log` directement sur la fenêtre
- **Argument en ligne de commande** : `python3 gps_viewer.py fichier.txt`
- Filtrage automatique des trames invalides (`fix_quality = 0`)

## Carte

- Affichage de la trace GPS sur une carte interactive rendue nativement (matplotlib + contextily)
- Marqueur de **départ** (cercle vert) et d'**arrivée** (carré rouge)
- **Zoom à la molette** centré sur le pointeur
- **Pan** par clic gauche + glisser
- **Recentrage** sur la trace complète : bouton `⌂ Recentrer` (Ctrl+R)

### Fonds de carte disponibles

| Source | Description |
|--------|-------------|
| OpenStreetMap | Carte standard (défaut) |
| Satellite Esri | Vue satellite mondiale |
| Orthophoto IGN | Photographies aériennes IGN France |
| Plan IGN | Cartographie topographique IGN France |

Changement via le bouton `🗺 Fond de carte` dans la barre d'outils ou le menu Navigation.

## Graphiques

- **Profil altimétrique** : altitude en mètres en fonction de la distance parcourue
- **Profil de vitesse** : vitesse en km/h calculée par différentiel Haversine entre trames successives, lissée sur 5 points
- Curseur rouge synchronisé : survoler un graphique déplace le repère sur la carte et réciproquement

## Panneau de statistiques

Affiché en permanence à droite de la carte :

| Statistique | Description |
|-------------|-------------|
| Fichier | Nom du fichier chargé |
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

## Enregistreur Arduino (gps_datalogger.ino)

- Lecture des trames NMEA via SoftwareSerial (pins 2/3, 9600 baud)
- Enregistrement sur carte SD via SdFat (CS = pin SS)
- Nommage automatique des fichiers : `GPS00.txt` → `GPS99.txt`
- Synchronisation SD à chaque trame pour éviter les pertes en cas de coupure
- Indicateur LED : clignotement rapide (init), lent (OK), fixe (erreur)
- Écho des trames sur le port série USB pour surveillance en temps réel
