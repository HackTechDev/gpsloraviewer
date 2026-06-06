# Améliorations possibles — GPS Viewer

## Données et formats

- **Export GPX / KML / GeoJSON** : permettre d'exporter la trace dans des formats standards utilisables dans d'autres outils (QGIS, Google Earth, Garmin, etc.)
- **Import GPX** : lire directement les fichiers GPX produits par des appareils GPS commerciaux, en plus du format NMEA brut
- **Validation checksum NMEA** : vérifier le checksum en fin de trame (`*XX`) pour rejeter silencieusement les trames corrompues — actuellement aucun contrôle d'intégrité
- **Filtrage HDOP** : rejeter automatiquement les points dont le HDOP dépasse un seuil configurable (ex : 5.0) pour améliorer la qualité des traces
- **Segmentation automatique** : détecter les pauses (vitesse nulle prolongée) et découper la trace en segments distincts avec des statistiques par segment
- **Détection de sauts GPS** : alerter si deux points consécutifs sont espacés de plus de 100 m sans cohérence temporelle (satellite perdu, redémarrage)
- **Dédoublonnage** : refuser le chargement d'un fichier déjà présent dans la session

## Carte

- **Export image carte** : sauvegarder la vue carte actuelle (trace + fond de carte) en PNG haute résolution
- **Affichage des waypoints** : marqueurs numérotés sur des points d'intérêt définis par l'utilisateur
- **Clustering d'annotations photo** : regrouper les photos proches en un symbole `N×` pour éviter la surcharge visuelle quand il y a beaucoup d'annotations
- **Sources de tuiles supplémentaires** : OpenTopoMap (topographie), CyclOSM (vélo), Stamen Terrain
- **Annulation des mesures de distance** : bouton dédié en plus de la touche Échap

## Vue 3D

- **Exagération verticale configurable** : slider pour multiplier l'axe Z et rendre le relief plus lisible sur les terrains plats
- **Extrusion du profil altimétrique** : afficher les murs verticaux sous la trace pour mieux visualiser le dénivelé
- **Animation** : rejouer le parcours sous forme d'un point se déplaçant sur la trace en 3D avec boutons play/pause/vitesse
- **Curseur 3D synchronisé** : le survol d'un graphique déplace également un repère dans la vue 3D
- **Export image 3D** : sauvegarder la vue 3D courante en PNG haute résolution
- **Simplification des traces 3D** : appliquer Douglas-Peucker sur les traces > 1 000 points pour éviter les ralentissements

## Graphiques

- **Courbes lissées** : interpolation spline (scipy) en option pour remplacer la ligne brisée actuelle
- **Lissage variable** : slider pour ajuster la fenêtre de lissage (3 à 21 points) en temps réel
- **Zoom sur intervalle** : cliquer-glisser sur un graphique pour zoomer sur un segment de la trace
- **Double-clic pour réinitialiser le zoom**
- **Tooltip au survol** : afficher la valeur exacte + temps + distance au point le plus proche du curseur
- **Annotations des points remarquables** : étiquettes automatiques sur le sommet (altitude max), le point le plus rapide, etc.
- **Graphique de pente** : pourcentage de pente calculé à partir de l'altitude et de la distance
- **Axe temporel** : option pour afficher les graphiques en fonction du temps au lieu de la distance
- **Graphique de fréquence cardiaque** : si les données FC sont disponibles dans le fichier GPS (appareils Garmin/Suunto)
- **Export graphique en PNG**

## Statistiques

- **Gain altimétrique** : afficher le cumul de montée et de descente (D+ / D−)
- **Pente moyenne** : pourcentage moyen sur l'ensemble du parcours
- **Temps en mouvement** : distinguer temps total et temps effectivement en déplacement (vitesse > seuil)
- **Vitesse moyenne en temps** : alternative à la vitesse moyenne en distance
- **Copie presse-papiers** : Ctrl+C pour copier les statistiques affichées sous forme texte tabulaire

## Interface

- **Persistance de la mise en page** : mémoriser la position du splitter, la source de tuiles active et le dernier niveau de zoom entre les sessions (`~/.config/gps_viewer.ini`)
- **Mode sombre** : thème sombre pour les graphiques, le panneau et la barre d'outils
- **Raccourcis clavier supplémentaires** : `+` / `-` pour zoomer, flèches pour pan
- **Plein écran** : touche F11 pour passer la carte en plein écran
- **Recherche de lieu (Nominatim)** : dans le dialog "Aller aux coordonnées", ajouter un champ de recherche par nom de lieu via l'API Nominatim d'OSM
- **Affichage EXIF dans le visionneur photo** : date de prise, modèle d'appareil, focale
- **Rotation de photo** : boutons ↶ ↷ dans le visionneur pour corriger l'orientation sans quitter l'application

## Enregistreur Arduino

- **Horodatage RTC** : ajouter un module RTC (DS3231) pour inscrire la date réelle dans le nom de fichier (`GPS_20250101.txt`)
- **Affichage OLED** : petit écran 128×32 affichant la position courante, la vitesse et l'état de la SD en temps réel
- **Bouton pause/reprise** : permettre de stopper l'enregistrement sans couper l'alimentation
- **Batterie et gestion d'énergie** : mode veille entre les trames pour réduire la consommation lors d'un usage sur batterie
- ~~**Transmission LoRa**~~ ✅ Implémenté — SF7 (défaut RadioHead), 434 MHz, portée ~2–5 km, 1 envoi toutes les 10 s (duty cycle EU433 < 1 %)

## Récepteur LoRa / Intégration PC

- ~~**Script de réception PC**~~ ✅ Implémenté — `lora_receiver.py` lit le port série, écrit les trames NMEA dans `tracks/gps/LORA_*.txt`, lisible dans GPS Viewer. Lanceur `runLoRaReceiver.sh` fourni.
- **Validation checksum dans lora_receiver.py** : vérifier le checksum NMEA avant d'écrire dans le fichier pour rejeter les trames corrompues par la liaison LoRa
- **Reconnexion automatique** : si le port série est déconnecté (Arduino débranché), tenter de se reconnecter périodiquement au lieu de planter
- **Baud rate configurable** : option `--baud` pour `lora_receiver.py` (actuellement 115200 codé en dur)
- **Affichage RSSI dans le terminal** : reformater les lignes `#` pour afficher le signal de façon plus lisible (ex : `[12] RSSI: -87 dBm`)
- **Réception temps réel dans GPS Viewer** : intégrer `lora_receiver.py` directement dans `gps_viewer.py` pour afficher la position live sur la carte sans fichier intermédiaire
- **ACK et qualité de liaison** : afficher le RSSI reçu dans l'interface GPS Viewer
- **Rejeu différé** : détecter automatiquement les fichiers `LORA_*.txt` dans `tracks/gps/` et les proposer à l'ouverture

## Réseau et partage

- **Affichage GPS en temps réel** : connexion directe à un module GPS série (USB ou Bluetooth) pour afficher la position en live sans passer par la carte SD
- **Export image** : sauvegarder la vue carte actuelle (avec la trace) en PNG/SVG haute résolution
- **Génération de rapport PDF** : rapport automatique incluant la carte, les graphiques et les statistiques
- **Serveur web embarqué** : option pour exposer la carte HTML sur le réseau local afin de la consulter depuis un smartphone
- **Carte HTML hors-ligne** : remplacer les CDN Chart.js par des ressources locales pour que `gps_map.py` fonctionne sans Internet
