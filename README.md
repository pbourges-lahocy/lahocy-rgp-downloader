# Lahocy RGP Downloader

Outil interne permettant aux équipes topographiques de Lahocy de télécharger simplement
les données RINEX du Réseau GNSS Permanent (RGP) de l'IGN, sans passer par l'interface
web de l'IGN (souvent indisponible ou peu pratique sur le terrain).

## Objectif

À partir de la position d'un chantier, d'une date et d'une plage horaire (ou d'une
journée entière), l'application :

1. détermine les stations RGP les plus proches ;
2. vérifie **en ligne** quelles données sont réellement disponibles (jamais une simple
   supposition à partir d'un catalogue statique) ;
3. permet de sélectionner les stations souhaitées ;
4. télécharge les fichiers RINEX nécessaires ;
5. les décompresse et les convertit (CRINEX/Hatanaka → RINEX) si besoin ;
6. produit un dossier directement exploitable dans un logiciel de post-traitement GNSS,
   avec un rapport de téléchargement.

## État du projet

Le développement suit une approche par phases (voir [docs/RGP_IGN.md](docs/RGP_IGN.md)
pour l'analyse complète du fonctionnement réel du serveur RGP IGN, vérifiée par
observation directe des serveurs) :

- ✅ **Phase 1** — Analyse du RGP IGN et documentation (`docs/RGP_IGN.md`).
- ✅ **Phase 2** — Prototype en ligne de commande (`scripts/cli.py`) :
  saisie de la position/date/horaires, recherche des stations proches, vérification
  réelle de la disponibilité, affichage exact des fichiers qui seraient téléchargés.
- ✅ **Phase 3** — Téléchargement réel (`scripts/cli.py --download DOSSIER`) :
  téléchargement effectif, décompression et conversion Hatanaka → RINEX, arborescence
  `RGP/AAAA-MM-JJ/STATION/`, rapport `rapport_RGP.txt`.
- ✅ **Phase 4** — Interface graphique (`scripts/gui.py`) : carte de France cliquable
  (Leaflet embarqué), synchronisation Lambert-93/WGS84/carte, recherche et sélection des
  stations avec disponibilité en temps réel, téléchargement et rapport en un clic.
- ✅ **Phase 5** — Exécutable Windows autonome (`LahocyRGPDownloader.spec`, PyInstaller) :
  aucune installation de Python requise pour les techniciens.

## Installation développeur

Prérequis : Python 3.12+ (testé avec 3.14).

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,gui]"
```

`gui` installe PySide6 (interface graphique + navigateur Leaflet embarqué) ; omettez-le
si seule la ligne de commande vous intéresse.

Sur un poste Windows d'entreprise avec inspection TLS (proxy/pare-feu), l'application
valide les certificats via le magasin de confiance du système d'exploitation
(bibliothèque `truststore`) plutôt que le bundle certifi embarqué — voir
`app/utils/http_client.py`.

## Lancement de l'interface graphique

```bash
python scripts/gui.py
```

- Cliquez sur la carte (ou saisissez X/Y Lambert-93 / latitude-longitude — les trois se
  synchronisent automatiquement) pour positionner le chantier.
- Renseignez la date et l'horaire (ou cochez « Journée entière »).
- Choisissez le nombre de stations souhaité, puis « Rechercher les stations RGP » :
  les 10 stations les plus proches s'affichent sur la carte et dans le tableau, avec leur
  disponibilité réelle (vérifiée en ligne). Les stations sont sélectionnables/désélectionnables.
- « Télécharger les données RGP » demande un dossier de destination, télécharge les
  fichiers des stations cochées, les rend exploitables, et écrit `rapport_RGP.txt`.
- Le panneau **Journal** affiche tous les avertissements et erreurs — rien n'est masqué.

La carte utilise Leaflet embarqué localement (`app/ui/assets/leaflet/`, aucune
dépendance CDN) avec les tuiles OpenStreetMap ; seules ces tuiles nécessitent une
connexion Internet (l'application en a de toute façon besoin pour le RGP). Si la carte
reste noire ou grise, voir la note GPU/QtWebEngine dans `scripts/gui.py`.

## Lancement de la ligne de commande

```bash
# Dry-run (Phase 2) : n'affiche que ce qui serait téléchargé, sans rien télécharger.
python scripts/cli.py --x 818372.47 --y 6966074.64 \
    --date 14/09/2026 --start 08:15 --end 17:45 --count 3

python scripts/cli.py --lat 48.8566 --lon 2.3522 \
    --date 14/09/2026 --full-day --count 5 --refresh-catalog

# Téléchargement réel (Phase 3) : ajoute --download vers un dossier destination.
python scripts/cli.py --lat 48.8566 --lon 2.3522 \
    --date 14/09/2026 --full-day --count 3 --download D:\Chantiers
```

Sans `--download` : affiche les stations les plus proches, leur disponibilité réelle
(vérifiée par requête HTTP sur `rgpdata.ign.fr`), et la liste exacte des fichiers qui
seraient téléchargés — rien n'est écrit sur le disque.

Avec `--download DOSSIER` : télécharge réellement les fichiers des stations
disponibles/partielles, les décompresse et les convertit (CRINEX → RINEX) dans
`DOSSIER/RGP/AAAA-MM-JJ/STATION/`, puis écrit `DOSSIER/RGP/AAAA-MM-JJ/rapport_RGP.txt`.

## Tests

```bash
pytest
```

Les tests ne dépendent pas du réseau : ils utilisent des fixtures reproduisant la
structure réelle du serveur IGN (`tests/fixtures/`).

## Génération de l'exécutable Windows

```bash
pip install -e ".[gui,build]"
pyinstaller LahocyRGPDownloader.spec
```

Produit `dist/LahocyRGPDownloader/LahocyRGPDownloader.exe` (mode "onedir" : un dossier
contenant l'exécutable et ses dépendances — recommandé pour les applications
QtWebEngine, plus rapide et plus fiable au démarrage qu'un exécutable "onefile"). Pour
distribuer l'application, copier tout le dossier `dist/LahocyRGPDownloader/` — aucune
installation de Python n'est nécessaire sur le poste du technicien.

Le spec bundle explicitement :
- les assets de la carte (`app/ui/assets/`, dont Leaflet embarqué) ;
- `config/config.yaml` ;
- les exécutables `hatanaka` (`crx2rnx.exe`/`rnx2crx.exe`) nécessaires à la conversion
  CRINEX → RINEX ;
- les données PROJ de `pyproj` (résolues automatiquement via `pyinstaller-hooks-contrib`).

En exécutable figé, le cache des stations (§14) est écrit dans
`%LOCALAPPDATA%\LahocyRGPDownloader\` plutôt qu'à côté de l'exécutable (qui peut se
trouver dans un dossier en lecture seule), voir `app/config/loader.py`.

### ⚠️ Avertissement Microsoft Defender SmartScreen

L'exécutable n'étant pas signé (aucun certificat de signature de code), Windows
SmartScreen affiche un avertissement « Windows a protégé votre ordinateur » au premier
lancement d'un fichier téléchargé depuis Internet — comportement normal pour tout `.exe`
non signé, et particulièrement fréquent pour les binaires PyInstaller. Sur un poste où
la stratégie de groupe a retiré le bouton « Exécuter quand même », seul un compte
administrateur peut passer outre.

Contournement sans droits admin, sur le fichier déjà téléchargé :

```powershell
Unblock-File -Path "chemin\vers\LahocyRGPDownloader-vX.Y.Z-win64.zip"
```

(à faire **avant** extraction du zip ; sinon débloquer chaque `.exe`/`.dll` un par un via
clic droit → Propriétés → case « Débloquer »).

Pour une distribution durable aux techniciens (qui n'ont pas non plus les droits admin),
deux pistes à arbitrer plus tard, indépendantes du code : diffuser via un canal interne
Lahocy (partage réseau/outil de déploiement IT — évite la marque « provient d'Internet »
qui déclenche SmartScreen) ou signer l'exécutable avec un certificat de signature de
code (élimine l'avertissement durablement, mais implique un coût et une démarche auprès
d'une autorité de certification).

## Architecture

```text
src/app/
├── ui/
│   ├── main_window.py   Fenêtre principale (PySide6)
│   ├── map_view.py       Widget carte (QWebEngineView + Leaflet embarqué)
│   ├── map_bridge.py      Pont Qt <-> JavaScript (QWebChannel)
│   ├── workers.py         Threads Qt pour les appels réseau (catalogue/recherche/téléchargement)
│   └── assets/            HTML de la carte + Leaflet local (JS/CSS/icônes, sans CDN)
├── rgp/
│   ├── catalog.py       Catalogue des stations (agrégé depuis les fiches logsheet IGS)
│   ├── stations.py      Modèle Station + recherche des plus proches
│   ├── availability.py  Vérification réelle de la disponibilité (HTTP HEAD)
│   ├── downloader.py    Téléchargement des fichiers sélectionnés
│   ├── rinex.py         Décompression (.Z/.gz) et conversion Hatanaka → RINEX
│   ├── report.py        Génération du rapport de téléchargement (rapport_RGP.txt)
│   └── provider_ign.py  SEUL module qui connaît la structure du serveur IGN
├── geo/
│   ├── coordinates.py   Lambert-93 <-> WGS84 (pyproj), parsing sexagésimal IGS
│   └── distance.py      Distance géodésique (pyproj.Geod)
├── config/
│   └── loader.py        Chargement de config/config.yaml
└── utils/
    ├── http_client.py   Client HTTP avec retry/timeout
    └── dates.py         Jour de l'année, sessions horaires RINEX, conversion fuseau
```

La logique spécifique à l'IGN est **entièrement isolée** dans `rgp/provider_ign.py` et
`config/config.yaml` : si l'IGN change son domaine, son arborescence ou son nommage de
fichiers, seuls ces deux éléments doivent être adaptés.

## Source des données

[Réseau GNSS Permanent (RGP)](https://rgp.ign.fr/) de l'IGN, serveur de données
`https://rgpdata.ign.fr` (accès public, licence Ouverte Etalab). Voir
[docs/RGP_IGN.md](docs/RGP_IGN.md) pour le détail de l'arborescence, des formats et des
conventions de nommage, établi par observation directe du serveur.
