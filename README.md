# YouTube Live Chat Monitor 🔍

Outil d'analyse en temps réel du chat YouTube Live pour **détecter les comportements suspects** (triche, bots, manipulation de votes).

## 🎯 Objectif

Pendant un live YouTube avec système de vote (les viewers tapent `1`, `2` ou `3` dans le chat), cet outil permet de :

- **Capturer l'intégralité du chat** en temps réel
- **Analyser les votes** et détecter les anomalies
- **Identifier les comportements suspects** :
  - 🤖 Comptes qui votent plusieurs fois
  - 🔄 Changements de vote suspects
  - 📊 Pics d'activité anormaux (spam/bots)
  - 👥 Comptes créés récemment qui votent en masse

## 🛡️ Redundant Capture (Multiple Methods)

Le script `yt_chat_backup.py` lance **3 méthodes de capture en parallèle** pour garantir qu'aucun message n'est perdu :

| Méthode | Lib | Cookies ? | Fiabilité |
|---------|-----|-----------|-----------|
| **Innertube API** | Custom scraper | ❌ Non | ⭐⭐⭐ Très fiable |
| **chat_downloader** | `chat-downloader` | ❌ Non | ⭐⭐ Fiable |
| **yt-dlp** | `yt-dlp` | ⚠️ Parfois | ⭐⭐ Dépend de l'IP |

À la fin, les 3 fichiers sont **fusionnés et dédupliqués** automatiquement.

```bash
# Lancer la capture redondante
python3 yt_chat_backup.py "URL_DU_LIVE" -o chat_backup

# Avec seulement certaines méthodes
python3 yt_chat_backup.py "URL" -m innertube,chatdl

# Avec durée max
python3 yt_chat_backup.py "URL" -d 3600  # 1 heure
```

Résultat dans `chat_backup/` :
- `chat_innertube_*.json` — Capture méthode 1
- `chat_chatdl_*.json` — Capture méthode 2
- `chat_ytdlp_*.json` — Capture méthode 3
- `chat_MERGED_*.json` — ✅ Fichier fusionné (toutes les méthodes combinées, dédupliqué)

## 📦 Installation

```bash
# Cloner le repo
git clone https://github.com/playAbilityTech/youtube-chat-monitor.git
cd youtube-chat-monitor

# Installer les dépendances
pip install -r requirements.txt
```

## 🚀 Utilisation

### 1. Capturer le chat en temps réel

```bash
# Lancer la capture pendant le live
python3 yt_chat_scraper.py "https://www.youtube.com/live/VIDEO_ID" -o chat.json
```

Le script :
- Se connecte au chat YouTube via l'API innertube (pas besoin de cookies)
- Poll toutes les 3 secondes en mode live
- Sauvegarde chaque message en temps réel (format JSONL)
- Déduplique automatiquement
- Affiche la progression dans le terminal

**Options :**
| Option | Description |
|--------|-------------|
| `-o FILE` | Fichier de sortie (défaut: `chat_VIDEOID.json`) |
| `-d SECONDS` | Durée max de capture (défaut: illimité) |

**Arrêter la capture :** `Ctrl+C` — les messages déjà capturés sont sauvegardés.

### 2. Analyser les votes

```bash
# Générer tous les graphiques d'analyse
python3 analyze_votes.py chat.json
```

Génère dans le dossier `vote_results/` :

| Fichier | Description |
|---------|-------------|
| `votes_10s.png` | Votes par tranche de 10 secondes (détection de pics) |
| `votes_1min.png` | Votes par minute |
| `votes_5min.png` | Votes par tranche de 5 minutes |
| `votes_cumulative.png` | Courbe cumulative des votes |
| `votes_final.png` | Résultat final (camembert) |
| `vote_changes.png` | Tableau des gens qui ont changé de vote |
| `votes.csv` | Données brutes exportées |

### 3. Monitoring en temps réel (pendant le live)

Pour surveiller en continu pendant le live, ouvrir **2 terminaux** :

**Terminal 1 — Capture :**
```bash
python3 yt_chat_scraper.py "URL_DU_LIVE" -o chat.json
```

**Terminal 2 — Analyse périodique :**
```bash
# Relancer l'analyse toutes les 30 secondes
watch -n 30 "python3 analyze_votes.py chat.json --output-dir vote_results && echo 'Updated!'"
```

Les graphiques dans `vote_results/` se mettent à jour automatiquement.

## 🔍 Ce qu'on surveille

### Indicateurs de triche
- **Multi-votes** : Quelqu'un qui envoie "1" 50 fois → le script ne compte que le dernier vote par personne
- **Vote switching** : Le tableau `vote_changes.png` montre qui a changé d'avis et combien de fois
- **Pics suspects** : Les graphiques 10s montrent si un afflux soudain de votes arrive d'un coup (bot raid)
- **Ratio votes/viewers** : Si le nombre de votants dépasse le nombre de viewers, y'a un problème

### Format des données

Chaque message est un objet JSON (une ligne par message) :
```json
{
  "author": {"name": "pseudo_youtube"},
  "timestamp": 1707836400.123,
  "message": "1"
}
```

## 📋 Prérequis

- Python 3.8+
- Connexion internet
- Pas besoin de compte YouTube ni de cookies

## 📄 Licence

Usage interne — PlayAbility Adaptive Software
