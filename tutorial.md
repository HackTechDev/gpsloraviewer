# Didacticiel — GPS Viewer

Ce didacticiel vous fait découvrir GPS Viewer pas à pas, en partant de zéro.
À la fin, vous saurez charger une trace, explorer la carte, lire les graphiques,
animer le parcours en 3D et ajouter vos premières annotations.

**Durée estimée :** 20 à 30 minutes  
**Fichier d'exemple :** `gps_viewer/tracks/gps/GPS08.txt` (trace de ~5 700 points)

---

## Étape 1 — Lancer l'application

```bash
cd gpslora/gps_viewer
./run.sh
```

Ou, si vous n'avez pas le script de lancement :

```bash
python3 gps_viewer.py
```

Un **écran de démarrage** s'affiche brièvement, puis la fenêtre principale apparaît.
Si c'est la première ouverture, la carte est vide et les graphiques sont grisés.

---

## Étape 2 — Créer un nouveau parcours

Un **parcours** est le fichier central (`.json`) qui regroupe vos traces GPS et vos
annotations. Commencez toujours par en créer un.

1. Menu **Fichier → Nouveau parcours…** (`Ctrl+N`).
2. Choisissez un dossier et nommez votre fichier, par exemple `mon_premier_parcours.json`.
3. Une boîte de dialogue vous propose un **titre** et une **description** — laissez-les
   vides pour l'instant et cliquez **OK**.

> La barre de titre affiche maintenant `GPS Viewer  [mon_premier_parcours.json]`.

---

## Étape 3 — Charger une trace GPS

1. Menu **Fichier → Ajouter une trace GPS…** (`Ctrl+O`), ou bouton **📂 Trace GPS**
   dans la barre d'outils.
2. Naviguez jusqu'à `gps_viewer/tracks/gps/` et sélectionnez **GPS08.txt**.
3. Cliquez **Ouvrir**.

**Ce que vous devez voir :**
- La trace GPS (ligne colorée) apparaît immédiatement sur la carte.
- Un fond de carte OpenStreetMap se charge en arrière-plan (quelques secondes).
- Le panneau **STATISTIQUES** à droite se remplit : distance, durée, D+/D−, vitesses.
- La barre de lecture apparaît en bas de la carte.
- Les deux graphiques (altitude et vitesse) affichent le profil de la trace.

> **Astuce :** Si les tuiles de fond tardent à arriver, la trace est déjà explorable
> — vous n'avez pas besoin d'attendre.

---

## Étape 4 — Explorer la carte

### Zoomer et se déplacer

| Action | Geste |
|--------|-------|
| Zoom avant / arrière | Molette de la souris |
| Déplacer la vue | Clic gauche + glisser |
| Revenir à la vue initiale | Bouton **⌂ Recentrer** ou `Ctrl+R` |

Essayez de zoomer sur le point de départ de la trace (marqueur **●**), puis recentrez.

### Changer le fond de carte

Cliquez sur **🗺 Fond de carte** dans la barre d'outils et choisissez
**Orthophoto IGN** pour voir les photographies aériennes sous la trace.
Revenez à **OpenStreetMap** ensuite.

### Changer la coloration de la trace

Cliquez sur **🎨 Trace** et sélectionnez **⚡ Vitesse**.
La trace passe d'une couleur unie à un dégradé vert → orange → rouge qui
révèle où vous étiez le plus rapide. Une **colorbar** apparaît en incrustation.

Repassez en **Couleur unie** avant de continuer.

---

## Étape 5 — Lire les graphiques

Déplacez la souris sur le **graphique altimétrique** (en bas à gauche).

**Ce que vous devez voir :**
- Un **trait rouge vertical** suit votre curseur sur le graphique.
- Sur la carte, un **point rouge** se déplace sur la trace à la position correspondante.
- Une **boîte sombre** à côté du point rouge affiche :
  - ↑ distance parcourue
  - ↓ distance restante
  - ⏱ temps écoulé depuis le départ
  - 🕐 heure GPS

Faites de même sur le **graphique de vitesse** (en bas à droite) : les deux graphiques
et la carte sont toujours synchronisés.

> **Conseil :** Le panneau CURSEUR à droite affiche en temps réel la latitude,
> la longitude, l'altitude, la vitesse et le nombre de satellites au point survolé.

---

## Étape 6 — Utiliser la barre de lecture

La barre de lecture en bas de la carte permet de *rejouer* le parcours automatiquement.

### Lancer la lecture

1. Cliquez sur **▶** (ou laissez la trace telle quelle — la lecture commence au début).
2. Le point rouge avance sur la trace, les graphiques suivent en temps réel.
3. Cliquez sur **⏸** pour mettre en pause.

### Changer la vitesse

Sélectionnez **× 5** dans le sélecteur de vitesse : le point avance 5 fois plus vite.
Essayez **× 10** pour parcourir la trace très rapidement.

### Utiliser le scrubber

La barre de progression sous les boutons représente la totalité de la trace.

- **Clic** à mi-chemin sur la barre → le curseur rouge saute immédiatement à ce point.
- **Glisser** la tête bleue → scrubbing continu ; la carte et les graphiques suivent
  pendant le glissement.
- Glisser pendant la lecture **suspend** automatiquement le timer et le reprend au
  relâchement.

> **Astuce :** Combinez scrubber et vitesse × 1 pour naviguer précisément sur un
> segment qui vous intéresse.

### Retour au début

Cliquez sur **⏮** pour revenir au point de départ.

---

## Étape 7 — Ajouter une annotation photo

Les annotations photo permettent de géolocaliser vos images directement sur la trace.

1. Cliquez sur le bouton **📷 Photo** dans la barre d'outils (ou appuyez sur `P`).
   Le curseur de la carte prend la forme d'une **croix**.
2. Cliquez à un endroit intéressant sur la trace (par exemple, près du sommet du profil
   altimétrique).
3. Un sélecteur de fichier s'ouvre — choisissez n'importe quelle image JPG ou PNG
   sur votre ordinateur.
4. Une **croix rouge** et une **miniature** apparaissent sur la carte, reliées par une
   petite flèche.

### Consulter la photo

Cliquez sur la croix rouge ou la miniature : la **visionneuse** s'ouvre avec :
- l'image en grand format ;
- les métadonnées EXIF si disponibles (date, modèle d'appareil, focale) ;
- des boutons de rotation **↶** (−90°) et **↷** (+90°) pour corriger l'orientation ;
- des champs **Titre** et **Description** — saisissez un titre, par exemple
  `Vue du sommet`, puis cliquez **Enregistrer**.

Appuyez sur `P` ou re-cliquez **📷 Photo** pour quitter le mode photo.

---

## Étape 8 — Ajouter une annotation note

Les notes permettent d'associer un texte libre à n'importe quel point de la carte.

1. Cliquez sur **📝 Note** dans la barre d'outils (ou appuyez sur `N`).
2. Cliquez sur la carte à l'endroit de votre choix.
3. La boîte de dialogue s'ouvre :
   - **Titre** : saisissez `Départ de randonnée`
   - **Description** : saisissez `Parking du col, départ à 08h30`
4. Cliquez **Enregistrer**.

Un **marqueur orange** apparaît sur la carte avec le titre au-dessus dans une étiquette
jaune pâle. Cliquez dessus pour modifier ou supprimer la note.

> Les modes **Photo** et **Note** sont mutuellement exclusifs : activer l'un désactive
> l'autre automatiquement. `Échap` quitte le mode actif.

---

## Étape 9 — Enregistrer le parcours

Appuyez sur `Ctrl+S` pour sauvegarder.

Le fichier `mon_premier_parcours.json` contient maintenant :
- le chemin vers `GPS08.txt` ;
- votre annotation photo (position, miniature, titre) ;
- votre annotation note (position, titre, description).

À la prochaine ouverture de l'application, ce parcours sera **rechargé automatiquement**
(ou via **Fichier → Fichiers récents JSON**).

---

## Étape 10 — Découvrir la vue 3D

1. Appuyez sur `Ctrl+3` ou allez dans **Navigation → Vue 3D**.
   Une fenêtre indépendante s'ouvre — vous pouvez la déplacer à côté de la fenêtre
   principale.

**Ce que vous devez voir :**
- La trace GPS en 3D avec l'axe altitude.
- La même trace **projetée sur le plan du sol** (vue du dessus), en transparence.
- Les marqueurs **●** (départ) et **■** (arrivée).
- Un fond de carte OSM en cours de chargement (plan horizontal en bas).

### Naviguer dans la vue 3D

| Geste | Action |
|-------|--------|
| Clic-glisser | Rotation de la caméra |
| Molette | Zoom avant / arrière |
| **⌂ Réinitialiser** | Retour à l'angle par défaut |

Faites pivoter la scène pour voir le relief sous différents angles.

### Animer le parcours

1. Cliquez sur **▶ Animer** dans la barre de lecture sous le canvas 3D.
2. Un **point blanc** (bordure colorée) se déplace sur la trace en altitude.
3. Un **disque** de même couleur avance en parallèle sur le plan du sol (son ombre).
4. Une **ligne verticale pointillée** relie les deux, indiquant l'altitude en temps réel.
5. Le compteur affiche :
   ```
   point 42 / 1 247  │  ↑ 1,3 km  ↓ 5,8 km  │  ⏱ 23 min  │  🕐 09:42
   ```

Essayez les vitesses **× 5** et **× 10** pour voir le relief défiler rapidement.
Glissez le **scrubber** pour sauter directement à un passage intéressant.

### Modes de coloration

Changez le mode de coloration en haut de la fenêtre :
- **🏔 Altitude** : la trace devient un dégradé de couleur selon l'altitude — les zones
  hautes ressortent clairement.
- **⚡ Vitesse** : identifiez visuellement les portions rapides et les montées lentes.

### Courbes de niveau SRTM

Cliquez sur **🏔 Courbes** : l'application télécharge les données d'altitude SRTM et
trace les courbes de niveau dans l'espace 3D. Le premier chargement prend quelques
secondes ; les données sont ensuite mises en cache.

---

## Étape 11 — Pour aller plus loin

Vous avez parcouru les fonctionnalités essentielles. Voici quelques pistes pour la suite :

### Comparer deux traces

1. **Fichier → Ajouter une trace GPS…** et chargez `GPS06.txt`.
2. Le sélecteur **📊 Graphiques :** apparaît dans la barre d'outils.
3. Choisissez **Toutes les traces GPS** pour superposer les deux profils sur les graphiques.
4. La vue 3D affiche automatiquement les deux traces, chacune avec sa couleur.

### Outils de mesure

Appuyez sur `Ctrl+D` pour activer la **mesure de distance** :
- Cliquez pour poser un point A, puis un point B → la distance s'affiche.
- Enchaînez les clics pour mesurer un itinéraire cumulé.
- `Échap` efface tout.

### Ajuster les préférences

**Paramétrage → Préférences…** (`Ctrl+,`) permet de personnaliser :
- l'épaisseur de la trace sur la carte,
- la taille du curseur rouge,
- la marge qui déclenche le recentrage automatique pendant la lecture,
- l'option de mémoriser la mise en page entre les sessions.

### Grille et miniature

- `Ctrl+L` : affiche une grille de coordonnées lat/lon adaptative.
- `Ctrl+M` : ouvre une miniature de localisation dans un coin de la carte.

---

## Récapitulatif des raccourcis utiles

| Raccourci | Action |
|-----------|--------|
| `Ctrl+N` | Nouveau parcours |
| `Ctrl+O` | Ajouter une trace GPS |
| `Ctrl+S` | Enregistrer |
| `Ctrl+R` | Recentrer la carte |
| `Ctrl+3` | Vue 3D |
| `Ctrl+D` | Mesure de distance |
| `Ctrl+L` | Grille de coordonnées |
| `Ctrl+M` | Miniature de localisation |
| `Ctrl+,` | Préférences |
| `P` | Mode annotation photo |
| `N` | Mode annotation note |
| `Échap` | Quitter le mode actif / effacer les mesures |
