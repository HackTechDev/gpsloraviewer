# Arduino — réglages du firmware

Notes sur les paramètres modifiables des firmwares Arduino de `gps_lora_logger/`.
Le câblage, les bibliothèques et l'installation sont décrits dans le
[README](README.md#système-dacquisition-arduino-gps_lora_logger).

## Période d'émission LoRa (`LORA_INTERVAL_MS`)

L'émetteur terrain (`gps_lora_logger/gps_lora_logger.ino`) enregistre sur la
carte SD **toutes** les trames du GPS (une par seconde), mais n'en envoie par
LoRa qu'**une toutes les 10 secondes** : la fenêtre « Données GPS reçues » et
la trace LoRa Live de GPS Viewer se mettent donc à jour toutes les 10 s.

La période est fixée par une constante, ligne 65 :

```c
#define LORA_INTERVAL_MS 10000UL   // en millisecondes
```

`sendLoRa()` ignore toute trame `$GPRMC` arrivant moins de `LORA_INTERVAL_MS`
après le dernier envoi.

### Modifier la valeur

1. Dans `gps_lora_logger/gps_lora_logger.ino`, changer la valeur, par exemple
   pour 5 s :
   ```c
   #define LORA_INTERVAL_MS 5000UL
   ```
   Mettre aussi à jour le commentaire au-dessus (lignes 61-64), qui justifie
   la valeur par le taux d'occupation du canal.
2. Dans `gps_viewer/lora_monitor.py`, mettre `_PERIOD_S` à la même valeur en
   secondes :
   ```python
   _PERIOD_S   = 5
   ```
   La fenêtre « Données GPS reçues » s'en sert pour colorer « Dernière trame
   il y a … s » (vert jusqu'à 1,5 × la période, orange jusqu'à 3 ×, rouge
   au-delà). Si on l'oublie, l'indicateur passe à l'orange trop tard (ou trop
   tôt).
3. **Reflasher l'Arduino terrain** (émetteur GPS + SD + LoRa) depuis l'IDE
   Arduino. Le récepteur branché au PC (`rf95_server.ino`) n'est pas concerné :
   il relaie ce qu'il reçoit, quel que soit le rythme.
4. Mettre à jour la documentation qui cite la période : README (section
   « Émetteur terrain »), FEATURES.md (section LoRa) et USER_GUIDE.md (§18,
   fenêtre « Données GPS reçues »).

### Contraintes à prendre en compte

**Occupation du canal radio.** Chaque envoi occupe l'antenne environ 70 ms
(SF7, BW 125 kHz, trame de ~75 octets). Le taux d'occupation vaut
`70 ms / période` :

| Période | Occupation du canal | Remarque |
|---------|---------------------|----------|
| 10 s (actuel) | ≈ 0,7 % | sous un duty cycle de 1 % |
| 7 s | ≈ 1,0 % | minimum pour un duty cycle de 1 % |
| 5 s | ≈ 1,4 % | au-delà de 1 % |
| 2 s | ≈ 3,5 % | |
| 1 s | ≈ 7 % | une trame GPS sur une |

La limite réglementaire dépend de la sous-bande utilisée dans la bande 433 MHz
et de la puissance d'émission (ETSI EN 300 220 / recommandation ERC 70-03) :
**la vérifier avant de descendre sous 7 s**. Le firmware actuel s'impose une
limite prudente de 1 %.

**Trames perdues sur la carte SD.** L'Arduino lit le GPS et le module LoRa par
deux ports série logiciels (`SoftwareSerial`), et ne peut en écouter qu'un à la
fois. Pendant chaque envoi LoRa (~70 à 100 ms), il n'écoute plus le GPS : les
caractères reçus pendant ce temps sont perdus et la trame en cours est
tronquée dans le fichier SD. Plus la période est courte, plus la trace SD
enregistrée compte de trames abîmées (rejetées ensuite par le contrôle de
checksum de GPS Viewer). À 10 s, l'effet est négligeable.

**Valeur minimale utile.** Le GPS produit une trame `$GPRMC` par seconde : une
période inférieure à 1 000 ms n'apporte rien (toutes les trames sont déjà
envoyées).
