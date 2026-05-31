# Améliorations possibles — GPS Viewer

## Données et formats

- **Export GPX / KML / GeoJSON** : permettre d'exporter la trace dans des formats standards utilisables dans d'autres outils (QGIS, Google Earth, Garmin, etc.)
- **Import GPX** : lire directement les fichiers GPX produits par des appareils GPS commerciaux, en plus du format NMEA brut
- **Segmentation automatique** : détecter les pauses (vitesse nulle prolongée) et découper la trace en segments distincts avec des statistiques par segment

## Carte

- **Affichage des waypoints** : marqueurs numérotés sur des points d'intérêt définis par l'utilisateur
- **Sources de tuiles supplémentaires** : OpenTopoMap (topographie), CyclOSM (vélo), Stamen Terrain

## Vue 3D

- **Extrusion du profil altimétrique** : afficher les murs verticaux sous la trace pour mieux visualiser le dénivelé
- **Animation** : rejouer le parcours sous forme d'un point se déplaçant sur la trace en 3D
- **Export image 3D** : sauvegarder la vue 3D courante en PNG haute résolution

## Graphiques

- **Graphique de fréquence cardiaque** : si les données FC sont disponibles dans le fichier GPS (appareils Garmin/Suunto)
- **Graphique de pente** : pourcentage de pente calculé à partir de l'altitude et de la distance
- **Axe temporel** : option pour afficher les graphiques en fonction du temps au lieu de la distance
- **Annotation des points remarquables** : étiquettes automatiques sur le sommet (altitude max), le point le plus rapide, etc.
- **Sélection d'intervalle** : cliquer-glisser sur un graphique pour zoomer sur un segment de la trace

## Interface

- **Mode sombre** : thème sombre pour les graphiques, le panneau et la barre d'outils
- **Raccourcis clavier supplémentaires** : `+` / `-` pour zoomer, flèches pour pan
- **Plein écran** : touche F11 pour passer la carte en plein écran
- **Sauvegarde de la mise en page** : mémoriser la position du splitter et les préférences de fond de carte entre les sessions (fichier `~/.config/gps_viewer.ini`)

## Enregistreur Arduino

- **Horodatage RTC** : ajouter un module RTC (DS3231) pour inscrire la date réelle dans le nom de fichier (`GPS_20250101.txt`)
- **Affichage OLED** : petit écran 128×32 affichant la position courante, la vitesse et l'état de la SD en temps réel
- **Bouton pause/reprise** : permettre de stopper l'enregistrement sans couper l'alimentation
- **Batterie et gestion d'énergie** : mode veille entre les trames pour réduire la consommation lors d'un usage sur batterie
- ~~**Transmission LoRa**~~ ✅ Implémenté — envoi des trames `$GPRMC` via RadioHead RH_RF95, rate-limité à 10 s (duty cycle EU)

## Récepteur LoRa / Intégration PC

- **Réception temps réel dans GPS Viewer** : lire le port Serial USB du récepteur (`rf95_server`) directement depuis `gps_viewer.py` pour afficher la position live sur la carte
- **ACK et qualité de liaison** : afficher le RSSI dans l'interface pour évaluer la portée LoRa en temps réel
- **Rejeu différé** : détecter automatiquement les fichiers `GPS*.txt` produits par l'émetteur terrain et les proposer à l'ouverture

## Réseau et partage

- **Affichage GPS en temps réel** : connexion directe à un module GPS série (USB ou Bluetooth) pour afficher la position en live sans passer par la carte SD
- **Export image** : sauvegarder la vue carte actuelle (avec la trace) en PNG/SVG haute résolution
- **Génération de rapport PDF** : rapport automatique incluant la carte, les graphiques et les statistiques
- **Serveur web embarqué** : option pour exposer la carte HTML sur le réseau local afin de la consulter depuis un smartphone
