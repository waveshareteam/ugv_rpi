# CLAUDE_SKILL_UGV — Documentation du Skill de Contrôle UGV

## Vue d'ensemble

Ce skill ajoute une couche REST sécurisée au-dessus de l'application Flask existante du robot UGV Waveshare. Il ne modifie pas l'interface Web existante et n'écrase aucun fichier.

### Fichiers ajoutés / modifiés

| Fichier | Type | Description |
|---------|------|-------------|
| `ugv_api.py` | Nouveau | Blueprint Flask avec les routes `/api/ugv/*` |
| `ugv_client.py` | Nouveau | Client CLI Python pour appeler l'API |
| `.claude/commands/ugv-control.md` | Nouveau | Skill Claude Code (`/ugv-control`) |
| `app.py` | Modifié (2 lignes) | Import + enregistrement du blueprint |

---

## Démarrage rapide

### 1. Démarrer le robot (sur le Raspberry Pi)

```bash
cd /path/to/ugv_rpi
python app.py
```

### 2. Vérifier que l'API répond

```bash
curl http://<ip-du-pi>:5000/api/ugv/status
```

### 3. Utiliser le skill dans Claude Code

Dans Claude Code, taper `/ugv-control` puis décrire ce que tu veux faire en français ou en anglais.

---

## Exemples de commandes

### "Avance doucement 1 seconde"

```bash
python ugv_client.py move forward --speed 0.3 --duration 1
```
ou via API :
```json
POST /api/ugv/move
{"direction": "forward", "speed": 0.3, "duration": 1.0}
```

---

### "Tourne à gauche"

```bash
python ugv_client.py move left --speed 0.3 --duration 0.8
```

---

### "Tourne à droite 2 secondes"

```bash
python ugv_client.py move right --speed 0.3 --duration 2
```

---

### "Recule lentement"

```bash
python ugv_client.py move backward --speed 0.2 --duration 1
```

---

### "Arrête tout" / "Stop d'urgence"

```bash
python ugv_client.py stop
```
ou :
```bash
curl -X POST http://<ip>:5000/api/ugv/stop
```

---

### "Prends une photo"

```bash
python ugv_client.py photo
```
Les photos sont sauvegardées dans `templates/pictures/`.

---

### "Démarre l'enregistrement vidéo"

```bash
python ugv_client.py video start
```

### "Arrête l'enregistrement"

```bash
python ugv_client.py video stop
```

---

### "Active la détection de visage"

```bash
python ugv_client.py cv face
```

### "Active la détection de mouvement"

```bash
python ugv_client.py cv motion
```

### "Désactive la vision par ordinateur"

```bash
python ugv_client.py cv none
```

### "Active l'autodrive" (⚠️ dangereux — nécessite confirmation)

```bash
python ugv_client.py cv autodrive --confirm
```

---

### "Allume les lumières de base"

```bash
python ugv_client.py lights --base 255 --head 0
```

### "Allume toutes les lumières"

```bash
python ugv_client.py lights --base 255 --head 255
```

### "Éteins toutes les lumières"

```bash
python ugv_client.py lights --base 0 --head 0
```

---

### "Regarde à gauche" (gimbal pan)

```bash
python ugv_client.py gimbal --x -45 --y 0
```

### "Regarde en haut"

```bash
python ugv_client.py gimbal --x 0 --y 30
```

### "Remets la caméra devant"

```bash
python ugv_client.py gimbal center
```

---

### "Donne-moi le statut du robot"

```bash
python ugv_client.py status
```

Exemple de réponse :
```json
{
  "status": "ok",
  "system": {
    "cpu_load": 12.5,
    "cpu_temp": 48.3,
    "ram_usage": 34.2,
    "wifi_rssi": -62,
    "wifi_mode": "STA",
    "wlan_ip": "192.168.1.42",
    "eth0_ip": null
  },
  "robot": {
    "voltage": 11.8,
    "base_light": 0,
    "head_light": 0,
    "cv_mode": 10301,
    "pan_angle": 0,
    "tilt_angle": 0,
    "video_recording": false,
    "video_fps": 25.3
  }
}
```

---

## Référence des endpoints REST

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/api/ugv/status` | Statut complet système + robot |
| POST | `/api/ugv/move` | Déplacement avec auto-stop |
| POST | `/api/ugv/stop` | Stop d'urgence immédiat |
| POST | `/api/ugv/lights` | Contrôle lumières base/tête |
| POST | `/api/ugv/gimbal` | Pan/tilt gimbal |
| POST | `/api/ugv/gimbal/center` | Recentrer la caméra |
| POST | `/api/ugv/photo` | Capture photo |
| POST | `/api/ugv/video/start` | Démarrer enregistrement |
| POST | `/api/ugv/video/stop` | Arrêter enregistrement |
| POST | `/api/ugv/cv/mode` | Changer mode détection CV |

---

## Règles de sécurité (appliquées par `ugv_api.py`)

1. **Durée max** : 5 secondes par commande de mouvement
2. **Vitesse max** : 0.8 (config.yaml : `max_speed: 1.3` mais limité par l'API)
3. **Vitesse défaut** : 0.3 (lent et sécuritaire)
4. **Auto-stop** : un timer Python annule le mouvement même si le client se déconnecte
5. **Autodrive** : nécessite `"confirm": true` dans le body JSON
6. **Stop d'urgence** : toujours disponible via `POST /api/ugv/stop`

---

## Utilisation via SSH

```bash
# Sur le Raspberry Pi
python ugv_client.py move forward --speed 0.3 --duration 1

# Depuis un autre poste, pointer vers le Pi
python ugv_client.py --host http://192.168.1.42:5000 status
```

---

## Architecture (couches)

```
Claude Code (/ugv-control skill)
        ↓
ugv_client.py (CLI Python)
        ↓
REST API /api/ugv/* (ugv_api.py Blueprint)
        ↓
app.py (Flask existant, non modifié fonctionnellement)
        ↓
base_ctrl.BaseController → UART → Robot
cv_ctrl.OpencvFuncs     → Caméra + CV
os_info.SystemInfo      → Infos système
```

L'interface Web existante (joystick, WebSocket, `/send_command`) reste **intacte**.
