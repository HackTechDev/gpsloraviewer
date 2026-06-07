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
- **Clustering de notes** : regrouper les notes proches de la même façon
- **Sources de tuiles supplémentaires** : OpenTopoMap (topographie), CyclOSM (vélo), Stamen Terrain
- **Annulation des mesures de distance** : bouton dédié en plus de la touche Échap

## Vue 3D

- ~~**Courbes de niveau SRTM**~~ ✅ Implémenté — bouton `🏔 Courbes`, données SRTM, courbes toutes les 50 m avec étiquettes
- ~~**Animation**~~ ✅ Implémenté — barre de lecture sous le canvas 3D : ⏮ ▶/⏸, vitesses ×1/×2/×5/×10, scrubber ; point animé 3D + shadow au sol + ligne verticale reliant les deux ; indicateurs ↑↓⏱🕐 en temps réel
- **Exagération verticale configurable** : slider pour multiplier l'axe Z et rendre le relief plus lisible sur les terrains plats
- **Extrusion du profil altimétrique** : afficher les murs verticaux sous la trace pour mieux visualiser le dénivelé
- **Curseur 3D synchronisé** : le survol d'un graphique déplace également un repère dans la vue 3D
- **Export image 3D** : sauvegarder la vue 3D courante en PNG haute résolution
- **Simplification des traces 3D** : appliquer Douglas-Peucker sur les traces > 1 000 points pour éviter les ralentissements

## Graphiques

- **Courbes lissées** : interpolation spline (scipy) en option pour remplacer la ligne brisée actuelle
- **Lissage variable** : slider pour ajuster la fenêtre de lissage (3 à 21 points) en temps réel
- **Zoom sur intervalle** : cliquer-glisser sur un graphique pour zoomer sur un segment de la trace
- **Double-clic pour réinitialiser le zoom**
- **Annotations des points remarquables** : étiquettes automatiques sur le sommet (altitude max), le point le plus rapide, etc.
- **Graphique de pente** : pourcentage de pente calculé à partir de l'altitude et de la distance
- **Axe temporel** : option pour afficher les graphiques en fonction du temps au lieu de la distance
- **Graphique de fréquence cardiaque** : si les données FC sont disponibles dans le fichier GPS (appareils Garmin/Suunto)
- **Export graphique en PNG**

## Statistiques

- ~~**Gain altimétrique D+ / D−**~~ ✅ Implémenté — affiché dans le panneau stats, la barre d'outils, la barre d'état et la vue 3D ; seuil 3 m pour filtrer le bruit GPS
- **Pente moyenne** : pourcentage moyen sur l'ensemble du parcours
- **Temps en mouvement** : distinguer temps total et temps effectivement en déplacement (vitesse > seuil)
- **Vitesse moyenne en temps** : alternative à la vitesse moyenne en distance
- **Copie presse-papiers** : Ctrl+C pour copier les statistiques affichées sous forme texte tabulaire

## Interface

- ~~**Persistance de la mise en page**~~ ✅ Implémenté — option dans Paramétrage → Préférences… ; mémorise la taille de fenêtre et la position des splitters dans `~/.config/gps_viewer/layout.json`
- ~~**Affichage EXIF dans le visionneur photo**~~ ✅ Implémenté — date de prise, modèle d'appareil, focale affichés dans la boîte de dialogue de visionneuse
- ~~**Rotation de photo**~~ ✅ Implémenté — boutons ↶ ↷ dans le visionneur pour corriger l'orientation sans quitter l'application
- **Mode sombre** : thème sombre pour les graphiques, le panneau et la barre d'outils
- **Raccourcis clavier supplémentaires** : `+` / `-` pour zoomer, flèches pour pan
- **Plein écran** : touche F11 pour passer la carte en plein écran
- **Recherche de lieu (Nominatim)** : dans le dialog "Aller aux coordonnées", ajouter un champ de recherche par nom de lieu via l'API Nominatim d'OSM

## Barre de lecture / Suivi

- ~~**Barre de lecture « Suivre »**~~ ✅ Implémenté — ⏮ ▶/⏸, vitesses ×1/×2/×5/×10, pan automatique, synchronisation graphiques
- ~~**Annotation curseur distance + temps**~~ ✅ Implémenté — boîte sombre : ↑ parcouru, ↓ restant, ⏱ temps écoulé, 🕐 heure GPS ; visible sur la carte et les deux graphiques
- ~~**Barre de progression de lecture (scrubber)**~~ ✅ Implémenté — slider pleine largeur sous les contrôles, clic/glisser pour se positionner librement
- **Curseur cliquable** : cliquer sur la trace pour positionner manuellement le curseur de lecture

## Annotations note

- ~~**Annotations note sur la carte**~~ ✅ Implémenté — bouton 📝 Note (touche N), marqueur orange, titre affiché, édition et suppression au clic, sauvegarde JSON
- **Icône personnalisable** : permettre de choisir la couleur ou le symbole du marqueur par note
- **Affichage de la description au survol** : tooltip ou popup au passage de la souris sans avoir à cliquer
- **Tri / liste des notes** : panneau latéral listant toutes les notes avec possibilité de cliquer pour centrer la carte sur la note
- **Export des notes** : inclure les notes dans un export GPX (waypoints) ou PDF

## Paramétrage

- ~~**Épaisseur de la trace**~~ ✅ Implémenté — Paramétrage → Préférences…
- ~~**Opacité du fond de carte**~~ ✅ Implémenté — Paramétrage → Préférences…
- ~~**Taille des marqueurs photo**~~ ✅ Implémenté — Paramétrage → Préférences…
- ~~**Taille du curseur rouge**~~ ✅ Implémenté — Paramétrage → Préférences…
- ~~**Marge de déclenchement du pan automatique**~~ ✅ Implémenté — Paramétrage → Préférences…
- **Seuil de dénivelé D+/D−** : rendre configurable le seuil de 3 m utilisé pour filtrer le bruit GPS
- **Fenêtre de lissage vitesse** : paramétrer la taille de la fenêtre de lissage (actuellement 5 points)
- **Couleurs de traces** : permettre de choisir la couleur de chaque trace manuellement

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
