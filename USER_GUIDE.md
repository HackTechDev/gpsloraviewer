# Guide d'utilisation — GPS Viewer

## Table des matières

1. [Présentation](#1-présentation)
2. [Démarrage](#2-démarrage)
3. [Créer un nouveau parcours](#3-créer-un-nouveau-parcours)
4. [Ouvrir un parcours existant](#4-ouvrir-un-parcours-existant)
5. [Ajouter des traces GPS](#5-ajouter-des-traces-gps)
6. [La carte interactive](#6-la-carte-interactive)
7. [La barre de lecture « Suivre »](#7-la-barre-de-lecture--suivre-)
8. [Les graphiques](#8-les-graphiques)
9. [Le panneau de statistiques](#9-le-panneau-de-statistiques)
10. [Les annotations photo](#10-les-annotations-photo)
11. [Les annotations note](#11-les-annotations-note)
12. [Outils cartographiques](#12-outils-cartographiques)
13. [La vue 3D](#13-la-vue-3d)
14. [Le menu Paramétrage](#14-le-menu-paramétrage)
15. [Enregistrer et gérer les fichiers](#15-enregistrer-et-gérer-les-fichiers)
16. [Raccourcis clavier](#16-raccourcis-clavier)
17. [Maintenance](#17-maintenance)

---

## 1. Présentation

GPS Viewer est une application desktop de visualisation de traces GPS. Elle permet de :

- charger une ou plusieurs traces GPS au format NMEA (`.txt`) sur une carte interactive ;
- comparer les profils altimétriques et de vitesse de chaque trace ;
- suivre automatiquement un parcours avec la barre de lecture ;
- annoter la carte avec des photos géolocalisées et des notes textuelles ;
- visualiser le parcours en trois dimensions avec courbes de niveau ;
- sauvegarder l'ensemble (traces + annotations) dans un fichier **parcours** (`.json`).

### Concept de « parcours »

Un **parcours** est un fichier `.json` qui regroupe :
- le titre et la description de la session ;
- les chemins vers les fichiers de traces GPS NMEA ;
- les annotations photo (position, image, titre, description, angle de vue).

C'est le document central de l'application. Il peut être partagé ou archivé ; il suffit de conserver les fichiers `.txt` et les photos aux mêmes emplacements absolus.

---

## 2. Démarrage

```bash
# Lancement simple
./run.sh

# Ou directement
python3 gps_viewer.py

# Avec un fichier JSON en argument
python3 gps_viewer.py mon_parcours.json
```

Au démarrage sans argument, l'application rouvre automatiquement le **dernier parcours utilisé**.

Un écran de démarrage s'affiche brièvement pendant le chargement. Pour personnaliser le logo, placez un fichier `logo.png` (carré, idéalement 96 × 96 px ou plus) à la racine du projet.

---

## 3. Créer un nouveau parcours

**Fichier → Nouveau parcours…** (`Ctrl+N`)

1. Une fenêtre de sélection de fichier s'ouvre — choisissez l'emplacement et le nom du fichier `.json` à créer.
2. Une boîte de dialogue vous propose de saisir un **titre** et une **description** (optionnels).
3. L'application se réinitialise : carte vide, graphiques vides, statistiques vides.
4. Le nouveau parcours est enregistré immédiatement et ajouté aux fichiers récents.

Vous pouvez ensuite ajouter des traces GPS et des annotations photo.

### Modifier le titre et la description

**Fichier → Propriétés du parcours…** (`Ctrl+I`) à tout moment pour modifier le titre et la description. Le titre apparaît dans la barre de titre de la fenêtre.

---

## 4. Ouvrir un parcours existant

**Fichier → Ouvrir…**

Sélectionnez un fichier `.json` existant. Les traces GPS et les annotations photo sont chargées automatiquement.

### Fichiers récents

**Fichier → Fichiers récents JSON** liste les 10 derniers parcours utilisés pour un accès rapide.

### Glisser-déposer

Il est possible de **glisser-déposer** un fichier `.txt` ou `.json` directement sur la fenêtre pour le charger.

---

## 5. Ajouter des traces GPS

### Ajouter une trace

**Fichier → Ajouter une trace GPS…** (`Ctrl+O`) ou bouton **📂 Trace GPS** dans la barre d'outils.

Sélectionnez un fichier NMEA (`.txt`, `.nmea`, `.log`). La trace s'affiche immédiatement sur la carte en attendant le chargement des tuiles de fond.

- Seules les trames `$GPGGA` avec un fix GPS valide sont lues.
- Les points sans fix (`fix_quality = 0`) sont automatiquement filtrés.

### Plusieurs traces simultanées

Répétez l'opération autant de fois que nécessaire. Chaque trace est affichée dans une couleur différente (palette de 8 couleurs cycliques). Un marqueur **●** indique le départ et un marqueur **■** indique l'arrivée de chaque trace.

Une **légende** apparaît en haut à gauche de la carte avec le nom de chaque fichier.

### Sélectionner la trace analysée

Dès que deux traces ou plus sont chargées, un sélecteur **📊 Graphiques :** apparaît dans la barre d'outils :

| Choix | Effet sur la carte | Effet sur les graphiques |
|-------|-------------------|--------------------------|
| Nom d'une trace | Seule cette trace est visible | Profils altimétrique et vitesse de cette trace uniquement |
| **Toutes les traces GPS** | Toutes les traces sont affichées | Les profils de toutes les traces sont superposés avec légende |

---

## 6. La carte interactive

### Navigation

| Geste | Action |
|-------|--------|
| Molette souris | Zoom avant / arrière centré sur le pointeur |
| Clic-glisser | Déplacer la vue (pan) |
| Bouton **⌂ Recentrer** (`Ctrl+R`) | Revenir à la vue initiale centrée sur toutes les traces |

### Fonds de carte

Le bouton **🗺 Fond de carte** dans la barre d'outils permet de choisir parmi :

| Source | Description |
|--------|-------------|
| OpenStreetMap | Carte standard avec routes et bâtiments (défaut) |
| Satellite (Esri) | Vue satellite mondiale |
| Orthophoto IGN | Photographies aériennes IGN (France) |
| Plan IGN | Cartographie topographique IGN (France) |

Les tuiles téléchargées sont mises en **cache** sur le disque (`~/.cache/gps_viewer/tiles/`) et réutilisées lors des sessions suivantes.

### Coloration de la trace

Le bouton **🎨 Trace** dans la barre d'outils propose trois modes de coloration :

| Mode | Description |
|------|-------------|
| Couleur unie | Couleur fixe par trace (comportement par défaut) |
| 🏔 Altitude | Gradient bleu → vert → jaune → rouge selon l'altitude |
| ⚡ Vitesse | Gradient vert → orange → rouge selon la vitesse |

### Boîte d'informations du curseur

Lorsque le curseur rouge se déplace sur la trace (via les graphiques ou la barre de lecture), une **boîte sombre** apparaît à côté du point rouge et affiche :

| Icône | Information |
|-------|-------------|
| ↑ | Distance parcourue depuis le départ |
| ↓ | Distance restante jusqu'à l'arrivée |
| ⏱ | Temps écoulé depuis le départ (ex : `42 min` ou `1h 07min`) |
| 🕐 | Heure GPS au point courant (HH:MM) |

Cette boîte est masquable via **Paramétrage → Afficher distance parcourue / restante**.

---

## 7. La barre de lecture « Suivre »

La barre de lecture apparaît **automatiquement** en bas de la carte dès qu'une trace GPS est chargée.

### Contrôles

| Élément | Description |
|---------|-------------|
| ⏮ | Revenir au point de départ |
| ▶ | Démarrer la lecture (le bouton devient ⏸) |
| ⏸ | Mettre en pause |
| Compteur | Affiche la position courante / nombre total de points |
| × 1 / × 2 / × 5 / × 10 | Sélectionner la vitesse de lecture |
| **Scrubber** (barre de progression) | Cliquer ou glisser pour se positionner librement sur la trace |

### Scrubber

La barre de progression sous les boutons représente l'intégralité de la trace. La tête bleue indique la position courante.

- **Clic** sur la barre → saute immédiatement à ce point ; le curseur rouge, les graphiques et la boîte d'informations se mettent à jour instantanément.
- **Glisser** → scrubbing continu ; le curseur suit en temps réel pendant le glissement.
- **Pendant la lecture** : glisser suspend automatiquement le timer et le reprend au relâchement depuis la nouvelle position.

### Pan automatique

Pendant la lecture, si le curseur rouge sort de la zone visible (ou dépasse la marge configurée), la carte se **recentre automatiquement** sur le curseur en conservant le niveau de zoom.

La marge de déclenchement est configurable dans **Paramétrage → Préférences…** (paramètre *Marge auto-pan*, en pixels).

### Synchronisation

Pendant la lecture, le curseur des deux graphiques et les valeurs du panneau statistiques (bloc CURSEUR) sont mis à jour en temps réel.

---

## 8. Les graphiques

### Profil altimétrique et profil de vitesse

Les deux graphiques en bas de fenêtre affichent respectivement :
- l'**altitude** (en mètres) en fonction de la distance parcourue ; une boîte de texte indique le D+ et le D−
- la **vitesse** (en km/h, lissée sur 5 points) en fonction de la distance

### Curseur synchronisé

Survolez un graphique avec la souris : un **trait rouge vertical** se déplace simultanément sur le graphique et le curseur rouge se positionne sur la trace GPS dans la carte. Le panneau de statistiques à droite affiche les valeurs en temps réel.

Une **boîte d'annotation** flottante s'affiche sur chaque graphique avec la même information que la boîte de la carte (distance parcourue, distance restante, temps écoulé, heure GPS).

### Mode multi-traces

Quand **Toutes les traces GPS** est sélectionné dans le combo **📊 Graphiques :**, les deux graphiques superposent les profils de toutes les traces avec une légende et des couleurs distinctes. Le curseur n'est pas actif dans ce mode.

### Changer la trace affichée

Utilisez le sélecteur **📊 Graphiques :** dans la barre d'outils (visible avec 2+ traces) pour choisir quelle trace est analysée dans les graphiques et les statistiques.

---

## 9. Le panneau de statistiques

Le panneau à droite affiche deux blocs :

**STATISTIQUES** — valeurs globales de la trace sélectionnée :

| Champ | Description |
|-------|-------------|
| Fichier | Nom du fichier NMEA |
| Points GPS | Nombre de positions valides |
| Distance | Distance totale en mètres |
| Durée | Durée totale de l'enregistrement |
| Altitude min / max | Altitudes extrêmes |
| Alt. moyenne | Altitude moyenne |
| D+ montée | Dénivelé positif cumulé (seuil 3 m) |
| D− descente | Dénivelé négatif cumulé (seuil 3 m) |
| Vitesse max | Vitesse maximale enregistrée |
| Vitesse moy. | Vitesse moyenne |

**CURSEUR** — valeurs en temps réel lors du survol d'un graphique ou pendant la lecture :
heure GPS, latitude, longitude, altitude, vitesse, distance cumulée, nombre de satellites.

> Le D+ et le D− sont également affichés dans la **barre d'outils** (en haut) et dans la **barre d'état** (en bas de fenêtre).

---

## 10. Les annotations photo

### Placer une photo

1. Activez le **mode photo** : bouton **📷 Photo** dans la barre d'outils, ou touche `P`.
   Le curseur de la carte prend la forme d'une croix.
2. **Cliquez** à l'endroit souhaité sur la carte.
3. Un sélecteur de fichier s'ouvre — choisissez votre image (JPG, PNG, BMP, GIF, TIFF, WebP).
4. L'image est copiée dans `tracks/images/` et une miniature 80 × 80 px est générée.
5. Une **croix rouge** et la miniature apparaissent sur la carte, reliées par une flèche.

### Consulter et modifier une annotation

Cliquez sur la croix rouge ou la miniature d'une annotation pour ouvrir la **visionneuse** :
- aperçu de la photo en plein format ;
- **métadonnées EXIF** : date de prise, modèle d'appareil, focale (si disponibles) ;
- boutons de **rotation** ↶ (−90°) et ↷ (+90°) pour corriger l'orientation de la photo ;
- champs **Titre** et **Description** éditables ;
- bouton **Supprimer** pour retirer l'annotation (les fichiers image sont également supprimés).

### Indicateur de direction (œil)

L'indicateur de direction matérialise l'angle de vue au moment de la prise de photo.

| Action | Touche |
|--------|--------|
| Survoler une annotation | — (hover) |
| Afficher / masquer l'indicateur | `V` |
| Tourner de +15° | `W` |
| Tourner de −15° | `X` |

---

## 11. Les annotations note

### Placer une note

1. Activez le **mode note** : bouton **📝 Note** dans la barre d'outils, ou touche `N`.
   Le curseur de la carte prend la forme d'une croix.
2. **Cliquez** à l'endroit souhaité sur la carte.
3. Une boîte de dialogue s'ouvre — saisissez un **Titre** et une **Description** (optionnelle).
4. Cliquez **Enregistrer** : un **marqueur orange** apparaît sur la carte avec le titre affiché au-dessus dans une étiquette jaune pâle.

> Les modes Photo et Note sont **mutuellement exclusifs** : activer l'un désactive l'autre automatiquement.
> `Échap` ou re-clic sur le bouton **📝 Note** quitte le mode note.

### Modifier ou supprimer une note

Cliquez sur le **marqueur orange** d'une note pour ouvrir le dialogue d'édition :
- champs **Titre** et **Description** pré-remplis et modifiables ;
- bouton **🗑 Supprimer** pour retirer définitivement la note.

### Sauvegarde

Les notes sont automatiquement sauvegardées dans le fichier parcours JSON (clé `"notes"`) et rechargées à la prochaine ouverture du parcours.

---

## 12. Outils cartographiques

### Grille de coordonnées (`Ctrl+L`)

Affiche / masque un quadrillage latitude / longitude adaptatif avec étiquettes de coordonnées. Le pas s'ajuste automatiquement au niveau de zoom.

### Miniature de localisation (`Ctrl+M`)

Affiche une vue d'ensemble de la trace dans un coin de la carte. Un rectangle rouge indique la portion actuellement visible.

### Mesure de distance (`Ctrl+D`)

Outil de mesure clic-à-clic :

1. Activez l'outil (bouton **📏 Mesure** ou `Ctrl+D`).
2. **Premier clic** : pose le point A.
3. **Déplacez** la souris : une ligne animée et la distance live s'affichent dans la barre de statut.
4. **Deuxième clic** : fige la mesure (la distance s'affiche sur la carte).
5. Vous pouvez enchaîner plusieurs mesures indépendantes.
6. Appuyez sur `Échap` pour effacer toutes les mesures.

### Navigation par coordonnées (`Ctrl+G`)

**Navigation → Aller aux coordonnées…** ou bouton **📍 Coordonnées**.

Saisissez une latitude et une longitude décimales (ou collez `48.8566, 2.3522`), choisissez le niveau de zoom, et la carte se centre sur ce point avec un repère rouge.

---

## 13. La vue 3D

**Navigation → Vue 3D** (`Ctrl+3`) ouvre une fenêtre 3D indépendante et non bloquante.

- La fenêtre affiche toutes les traces GPS chargées avec les axes Est / Nord (en mètres) et l'axe Altitude.
- Les marqueurs **●** (départ) et **■** (arrivée) sont visibles pour chaque trace.
- Chaque trace est aussi **projetée sur le plan du sol** (vue du dessus) avec la même couleur, permettant de lire le trajet à plat sans changer l'angle de caméra.
- Une **barre de statistiques** en bas indique pour chaque trace : distance, D+, D−, altitude min–max.

### Modes de coloration

Sélectionnables via les boutons en haut de la fenêtre :

| Mode | Description |
|------|-------------|
| Couleur unie | Couleur fixe par trace |
| 🏔 Altitude | Gradient selon l'altitude, colorbar affichée |
| ⚡ Vitesse | Gradient selon la vitesse, colorbar affichée |

### Fond de carte OSM

Le bouton **🗺 Fond OSM** ajoute un plan OpenStreetMap en base de la scène 3D :
- Masqué automatiquement pendant la rotation pour la fluidité, réaffiché au relâchement.
- Trois résolutions disponibles : **Basse** (64 px), **Moyenne** (128 px), **Haute** (256 px).

### Courbes de niveau SRTM

Le bouton **🏔 Courbes** calcule et affiche les courbes de niveau issues des données d'altitude SRTM, espacées de 50 m, avec étiquettes d'altitude sur la carte.

### Animation du parcours

Une **barre de lecture** (fond sombre) sous le canvas 3D permet de rejouer le parcours :

| Contrôle | Description |
|----------|-------------|
| ⏮ | Retour au point de départ |
| ▶ Animer | Démarrer l'animation (devient ⏸ Pause) |
| ⏸ Pause | Suspendre l'animation |
| × 1 / × 2 / × 5 / × 10 | Vitesse de lecture (points par tick de 100 ms) |
| **Scrubber** | Glissière pleine largeur — cliquer ou glisser pour se positionner |

Pendant l'animation, trois éléments se déplacent en synchronisation pour chaque trace :

| Élément | Description |
|---------|-------------|
| **Point 3D** | Cercle blanc avec bordure colorée, positionné à l'altitude réelle |
| **Shadow** | Disque de la couleur de la trace, projeté sur le plan du sol |
| **Ligne verticale** | Trait pointillé reliant le point 3D à son ombre — longueur = altitude relative |

Le compteur affiche en permanence :

```
point 42 / 1 247  │  ↑ 1,3 km  ↓ 5,8 km  │  ⏱ 23 min  │  🕐 09:42
```

> Les indicateurs ↑ ↓ ⏱ 🕐 sont basés sur la première trace chargée.
> Glisser le scrubber pendant la lecture suspend le timer et le reprend au relâchement.

### Navigation 3D

| Geste | Action |
|-------|--------|
| Clic-glisser | Rotation de la caméra |
| Molette | Zoom avant / arrière |
| Bouton **⌂ Réinitialiser la vue** | Retour à l'angle par défaut (élév. 25°, azim. −60°) |

> La caméra ne peut pas passer sous le plan horizontal (élévation ≥ 0°).

---

## 14. Le menu Paramétrage

### Afficher distance parcourue / restante

Bascule cochée par défaut. Décochez pour masquer la **boîte d'informations** (distance, temps, heure) à côté du curseur rouge sur la carte et dans les graphiques.

### Préférences… (`Ctrl+,`)

La boîte de dialogue Préférences applique chaque modification **immédiatement** (pas besoin de valider).

**Paramètres Carte**

| Paramètre | Valeur par défaut | Description |
|-----------|-------------------|-------------|
| Épaisseur de la trace | 2,5 px | Épaisseur du trait GPS sur la carte |
| Opacité fond de carte | 100 % | Transparence des tuiles (glissière 0–100 %) |
| Taille icônes photo | 0,8 | Facteur de zoom des miniatures sur la carte |
| Taille croix photo | 16 px | Taille de la croix rouge des annotations photo |
| Taille curseur rouge | 12 px | Diamètre du point rouge se déplaçant sur la trace |
| Marge auto-pan | 0 px | Distance au bord déclenchant le recentrage automatique pendant la lecture (0 = seulement quand le curseur sort de la vue) |

**Paramètre Général**

| Paramètre | Description |
|-----------|-------------|
| Mémoriser la mise en page | Si coché, la taille de la fenêtre et la position des séparateurs sont restaurées à la prochaine ouverture |

> Les préférences sont enregistrées dans `~/.config/gps_viewer/settings.json`.
> La mise en page est enregistrée dans `~/.config/gps_viewer/layout.json`.

---

## 15. Enregistrer et gérer les fichiers

| Action | Raccourci | Description |
|--------|-----------|-------------|
| **Enregistrer** | `Ctrl+S` | Sauvegarde dans le fichier parcours actif |
| **Enregistrer sous…** | `Ctrl+Shift+S` | Sauvegarde dans un nouveau fichier |
| **Nouveau parcours…** | `Ctrl+N` | Réinitialise et crée un nouveau fichier |
| **Ouvrir…** | — | Charge un fichier parcours existant |

L'application **sauvegarde automatiquement** après chaque ajout ou modification d'annotation photo.

La **barre de titre** affiche toujours le fichier parcours actif et la trace GPS chargée :
```
GPS Viewer  [mon_parcours.json]  Mon titre  — GPS03.txt
```

---

## 16. Raccourcis clavier

| Raccourci | Action |
|-----------|--------|
| `Ctrl+N` | Nouveau parcours |
| `Ctrl+O` | Ajouter une trace GPS |
| `Ctrl+S` | Enregistrer |
| `Ctrl+Shift+S` | Enregistrer sous… |
| `Ctrl+I` | Propriétés du parcours (titre / description) |
| `Ctrl+R` | Recentrer la carte sur la trace |
| `Ctrl+T` | Changer le fond de carte |
| `Ctrl+L` | Afficher / masquer la grille de coordonnées |
| `Ctrl+M` | Afficher / masquer la miniature |
| `Ctrl+D` | Activer / désactiver l'outil de mesure |
| `Ctrl+G` | Naviguer vers des coordonnées |
| `Ctrl+3` | Ouvrir / fermer la vue 3D |
| `Ctrl+,` | Ouvrir les Préférences |
| `Ctrl+Q` | Quitter |
| `P` | Activer / désactiver le mode annotation photo |
| `N` | Activer / désactiver le mode annotation note |
| `V` | Afficher / masquer l'indicateur de direction (œil) |
| `W` | Tourner l'indicateur de +15° |
| `X` | Tourner l'indicateur de −15° |
| `Échap` | Quitter le mode photo / note / mesure (ou effacer les mesures) |

---

## 17. Maintenance

### Cache de tuiles

Les tuiles cartographiques sont stockées dans `~/.cache/gps_viewer/tiles/`.

- **Outils → Informations sur le cache** : affiche le chemin, la taille en Mo et le nombre de fichiers.
- **Outils → Vider le cache** : supprime toutes les tuiles (confirmation demandée). Les tuiles seront re-téléchargées à la prochaine utilisation.

### Fichiers de configuration

| Fichier | Contenu |
|---------|---------|
| `~/.config/gps_viewer/last_track.txt` | Chemin du dernier parcours ouvert |
| `~/.config/gps_viewer/recent_tracks.json` | Liste des 10 derniers parcours utilisés |
| `~/.config/gps_viewer/settings.json` | Préférences (épaisseur trace, opacité, tailles, marge auto-pan…) |
| `~/.config/gps_viewer/layout.json` | Mise en page (taille fenêtre, position des séparateurs) |
| `~/.cache/gps_viewer/tiles/` | Cache persistant des tuiles cartographiques |

### Structure des fichiers du projet

```
gpslora/
├── gps_viewer/
│   ├── gps_viewer.py      # Fenêtre principale + point d'entrée
│   ├── map_canvas.py      # Widget carte (matplotlib + contextily)
│   ├── chart_canvas.py    # Graphiques altitude / vitesse
│   ├── stats_panel.py     # Panneau de statistiques
│   ├── gps_nmea.py        # Parseur NMEA et modèle de données GPS
│   ├── dialogs.py         # Boîtes de dialogue (coordonnées, photo, parcours, préférences)
│   ├── view_3d.py         # Vue 3D (matplotlib mpl_toolkits)
│   ├── lora_receiver.py   # Réception trames LoRa via port série
│   ├── logo.png           # Logo du splash screen (à créer)
│   ├── run.sh             # Script de lancement
│   └── tracks/
│       └── images/        # Photos annotées et leurs miniatures
├── gps_lora_logger/       # Firmware Arduino émetteur terrain
└── rf95_server/           # Firmware Arduino récepteur base LoRa
```
