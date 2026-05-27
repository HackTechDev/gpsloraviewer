# Guide d'utilisation — GPS Viewer

## Table des matières

1. [Présentation](#1-présentation)
2. [Démarrage](#2-démarrage)
3. [Créer un nouveau parcours](#3-créer-un-nouveau-parcours)
4. [Ouvrir un parcours existant](#4-ouvrir-un-parcours-existant)
5. [Ajouter des traces GPS](#5-ajouter-des-traces-gps)
6. [La carte interactive](#6-la-carte-interactive)
7. [Les graphiques](#7-les-graphiques)
8. [Le panneau de statistiques](#8-le-panneau-de-statistiques)
9. [Les annotations photo](#9-les-annotations-photo)
10. [Outils cartographiques](#10-outils-cartographiques)
11. [Enregistrer et gérer les fichiers](#11-enregistrer-et-gérer-les-fichiers)
12. [Raccourcis clavier](#12-raccourcis-clavier)
13. [Maintenance](#13-maintenance)

---

## 1. Présentation

GPS Viewer est une application desktop de visualisation de traces GPS. Elle permet de :

- charger une ou plusieurs traces GPS au format NMEA (`.txt`) sur une carte interactive ;
- comparer les profils altimétriques et de vitesse de chaque trace ;
- annoter la carte avec des photos géolocalisées ;
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

### Sélectionner la trace affichée dans les graphiques

Dès que deux traces ou plus sont chargées, un sélecteur **📊 Graphiques :** apparaît dans la barre d'outils. Choisissez la trace dont vous souhaitez voir le profil altimétrique, la courbe de vitesse et les statistiques. Le curseur sur la carte se synchronise avec la trace sélectionnée.

---

## 6. La carte interactive

### Navigation

| Geste | Action |
|-------|--------|
| Molette souris | Zoom avant / arrière |
| Clic-glisser | Déplacer la vue (pan) |
| Bouton **⌂ Recentrer** (`Ctrl+R`) | Revenir à la vue initiale centrée sur la trace |

### Fonds de carte

Le bouton **🗺 Fond de carte** (`Ctrl+T`) dans la barre d'outils permet de choisir parmi :

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

---

## 7. Les graphiques

### Profil altimétrique et profil de vitesse

Les deux graphiques en bas de fenêtre affichent respectivement :
- l'**altitude** (en mètres) en fonction de la distance parcourue ;
- la **vitesse** (en km/h, lissée sur 5 points) en fonction de la distance.

### Curseur synchronisé

Survolez un graphique avec la souris : un **curseur rouge** se déplace simultanément sur le graphique et sur la trace GPS dans la carte. Le panneau de statistiques à droite affiche les valeurs en temps réel à la position du curseur (heure, coordonnées, altitude, vitesse, distance, nombre de satellites).

### Changer la trace affichée

Utilisez le sélecteur **📊 Graphiques :** dans la barre d'outils (visible avec 2+ traces) pour choisir quelle trace est analysée dans les graphiques et les statistiques.

---

## 8. Le panneau de statistiques

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
| Vitesse max | Vitesse maximale enregistrée |
| Vitesse moy. | Vitesse moyenne |

**CURSEUR** — valeurs en temps réel lors du survol d'un graphique :
heure GPS, latitude, longitude, altitude, vitesse, distance cumulée, nombre de satellites.

---

## 9. Les annotations photo

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

## 10. Outils cartographiques

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

Saisissez une latitude et une longitude décimales, choisissez le niveau de zoom, et la carte se centre sur ce point avec un repère rouge.

---

## 11. Enregistrer et gérer les fichiers

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

## 12. Raccourcis clavier

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
| `Ctrl+Q` | Quitter |
| `P` | Activer / désactiver le mode annotation photo |
| `V` | Afficher / masquer l'indicateur de direction (œil) |
| `W` | Tourner l'indicateur de +15° |
| `X` | Tourner l'indicateur de −15° |
| `Échap` | Effacer toutes les mesures de distance |

---

## 13. Maintenance

### Cache de tuiles

Les tuiles cartographiques sont stockées dans `~/.cache/gps_viewer/tiles/`.

- **Outils → Informations sur le cache** : affiche le chemin, la taille en Mo et le nombre de fichiers.
- **Outils → Vider le cache** : supprime toutes les tuiles (confirmation demandée). Les tuiles seront re-téléchargées à la prochaine utilisation.

### Fichiers de configuration

| Fichier | Contenu |
|---------|---------|
| `~/.config/gps_viewer/last_track.txt` | Chemin du dernier parcours ouvert |
| `~/.config/gps_viewer/recent_tracks.json` | Liste des 10 derniers parcours utilisés |
| `~/.cache/gps_viewer/tiles/` | Cache persistant des tuiles cartographiques |

### Structure des fichiers du projet

```
gpslora/
├── gps_viewer.py      # Fenêtre principale + point d'entrée
├── map_canvas.py      # Widget carte (matplotlib + contextily)
├── chart_canvas.py    # Graphiques altitude / vitesse
├── stats_panel.py     # Panneau de statistiques
├── gps_nmea.py        # Parseur NMEA et modèle de données GPS
├── dialogs.py         # Boîtes de dialogue (coordonnées, photo, parcours)
├── logo.png           # Logo du splash screen (à créer)
├── run.sh             # Script de lancement
└── tracks/
    └── images/        # Photos annotées et leurs miniatures
```
