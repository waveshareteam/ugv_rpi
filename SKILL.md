---
name: ugv-control
description: Contrôle le robot UGV Waveshare (Raspberry Pi) via l'API REST Flask. Déclenche ce skill quand l'utilisateur veut faire bouger le robot, contrôler les lumières, la caméra, la détection CV, prendre une photo, enregistrer une vidéo, ou demander le statut du robot. Mots-clés déclencheurs : robot, UGV, avance, recule, tourne, stop, lumière, caméra, photo, vidéo, visage, mouvement, autodrive, gimbal, pan, tilt, statut robot.
---

# UGV Robot Control Skill

Tu contrôles un robot UGV Waveshare basé sur Raspberry Pi via son API REST Flask.
L'API tourne sur le Pi et expose des endpoints `/api/ugv/*`.

## Connexion

URL par défaut : `http://<ip-du-pi>:5000`
Vérifier que le Flask est actif : `GET /api/ugv/status`

Si l'adresse IP n'est pas connue, demander à l'utilisateur ou lire le statut ZeroTier.

## Endpoints disponibles

```
GET  /api/ugv/status              → statut système + robot complet
POST /api/ugv/move                → déplacement (auto-stop obligatoire)
POST /api/ugv/stop                → stop d'urgence immédiat
POST /api/ugv/lights              → contrôle lumières base et tête
POST /api/ugv/gimbal              → pan/tilt caméra
POST /api/ugv/gimbal/center       → recentrer caméra
POST /api/ugv/photo               → prendre une photo
POST /api/ugv/video/start         → démarrer enregistrement
POST /api/ugv/video/stop          → arrêter enregistrement
POST /api/ugv/cv/mode             → changer mode détection CV
```

## Règles de sécurité — TOUJOURS respecter

1. **Vitesse par défaut : 0.3** (jamais plus de 0.8 sans demande explicite)
2. **Durée max : 5 secondes** par commande de mouvement
3. **Auto-stop** : le serveur arrête le robot automatiquement après `duration`
4. **Avant tout mouvement** : vérifier que `/api/ugv/status` répond
5. **autodrive** requiert `"confirm": true` dans le body — toujours prévenir l'utilisateur
6. **Stop d'urgence** : `POST /api/ugv/stop` — toujours disponible

## Mapping intention → API

| L'utilisateur dit | Appel API |
|-------------------|-----------|
| "avance doucement" | POST /move {"direction":"forward","speed":0.3,"duration":1} |
| "avance X secondes" | POST /move {"direction":"forward","speed":0.3,"duration":X} |
| "recule" | POST /move {"direction":"backward","speed":0.3,"duration":1} |
| "tourne à gauche" | POST /move {"direction":"left","speed":0.3,"duration":0.8} |
| "tourne à droite" | POST /move {"direction":"right","speed":0.3,"duration":0.8} |
| "stop" / "arrête tout" | POST /stop |
| "allume lumières" | POST /lights {"base":255,"head":255} |
| "éteins lumières" | POST /lights {"base":0,"head":0} |
| "lumière base on/off" | POST /lights {"base":255,"head":0} ou {"base":0,"head":0} |
| "lumière tête on/off" | POST /lights {"base":0,"head":255} ou {"base":0,"head":0} |
| "regarde à gauche" | POST /gimbal {"x":-45,"y":0,"speed":200} |
| "regarde à droite" | POST /gimbal {"x":45,"y":0,"speed":200} |
| "regarde en haut" | POST /gimbal {"x":0,"y":30,"speed":200} |
| "regarde devant" / "centre caméra" | POST /gimbal/center |
| "prends une photo" | POST /photo |
| "démarre enregistrement" | POST /video/start |
| "arrête enregistrement" | POST /video/stop |
| "active détection visage" | POST /cv/mode {"mode":"face"} |
| "active détection mouvement" | POST /cv/mode {"mode":"motion"} |
| "active détection objets" | POST /cv/mode {"mode":"objects"} |
| "active suivi couleur" | POST /cv/mode {"mode":"color"} |
| "désactive CV" | POST /cv/mode {"mode":"none"} |
| "active autodrive" | POST /cv/mode {"mode":"autodrive","confirm":true} — AVERTIR L'UTILISATEUR |
| "statut du robot" | GET /status |

## Paramètres valides

**Mouvement (`/api/ugv/move`) :**
- `direction` : `forward`, `backward`, `left`, `right`, `spin_left`, `spin_right`
- `speed` : `0.0` à `0.8` (défaut `0.3`)
- `duration` : `0.1` à `5.0` secondes (défaut `1.0`)

**Gimbal (`/api/ugv/gimbal`) :**
- `x` : `-180` à `180` (pan, défaut `0`)
- `y` : `-30` à `90` (tilt, défaut `0`)
- `speed` : `1` à `1000` (défaut `200`)

**Lumières (`/api/ugv/lights`) :**
- `base` : `0`–`255`
- `head` : `0`–`255`

**Modes CV (`/api/ugv/cv/mode`) :**
- `none`, `motion`, `face`, `objects`, `color`, `autodrive`, `hand`, `mp_face`, `pose`

## Exécution des commandes

### Si SSH disponible sur le Pi :
```bash
python ugv_client.py move forward --speed 0.3 --duration 1
python ugv_client.py stop
python ugv_client.py status
python ugv_client.py --host http://<ip>:5000 status
```

### Via curl depuis n'importe quelle machine :
```bash
curl -X POST http://<ip>:5000/api/ugv/stop
curl -X POST http://<ip>:5000/api/ugv/move \
     -H "Content-Type: application/json" \
     -d '{"direction":"forward","speed":0.3,"duration":1.0}'
curl http://<ip>:5000/api/ugv/status
```

### Via le navigateur (extension Chrome MCP) :
```javascript
await fetch('http://<ip>:5000/api/ugv/status').then(r => r.json())
await fetch('http://<ip>:5000/api/ugv/stop', {method:'POST'})
await fetch('http://<ip>:5000/api/ugv/move', {
  method: 'POST',
  headers: {'Content-Type':'application/json'},
  body: JSON.stringify({direction:'forward', speed:0.3, duration:1.0})
}).then(r => r.json())
```

## Format de réponse standard

Après chaque commande, confirmer :
```
### UGV — [Action]
✅ Commande envoyée

| Paramètre | Valeur |
|-----------|--------|
| direction | forward |
| speed | 0.3 |
| duration | 1.0s |

Réponse API : {"status": "ok", ...}
```

## Vérification initiale (faire en premier)

Avant toute commande de mouvement :
1. `GET /api/ugv/status` — vérifier que Flask répond
2. Confirmer que `wlan_ip` ou `eth0_ip` est présent dans la réponse
3. Vérifier `voltage` > 10.5V (batterie suffisante)
4. Si `video_recording: true`, prévenir l'utilisateur

## Gestion d'erreurs

- **Connexion refusée** → Flask pas actif, dire à l'utilisateur de démarrer `python app.py` sur le Pi
- **400 sur autodrive** → ajouter `"confirm": true` et prévenir l'utilisateur du danger
- **Direction inconnue** → vérifier l'orthographe, utiliser les valeurs du tableau ci-dessus
- **Timeout** → le robot s'est peut-être déjà arrêté, envoyer `/stop` par précaution
