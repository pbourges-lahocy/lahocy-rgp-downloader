# Changelog

Toutes les modifications notables de ce projet sont documentées ici.

## [Non publié]

- Documentation de l'avertissement Microsoft Defender SmartScreen au lancement de
  l'exécutable non signé (contournement `Unblock-File` sans droits admin, pistes de
  distribution durable à arbitrer plus tard) — voir README.

## [0.1.0] - 2026-09-15

### Phase 5 — Exécutable Windows autonome

- `LahocyRGPDownloader.spec` : configuration PyInstaller (mode "onedir") bundlant les
  assets de la carte, `config/config.yaml`, les binaires `hatanaka` (CRX2RNX/RNX2CRX)
  et les données PROJ de `pyproj`.
- `app/config/loader.py` : résolution de `config.yaml` et du dossier de cache adaptée
  à l'exécution en exécutable figé (`sys.frozen`/`sys._MEIPASS`), avec le cache écrit
  dans `%LOCALAPPDATA%\LahocyRGPDownloader\` plutôt qu'à côté de l'exécutable.
- Validé par un test manuel de bout en bout sur l'exécutable compilé : conversion de
  coordonnées (pyproj), accès réseau au serveur RGP (truststore), chargement du
  catalogue, recherche de stations et avertissements identiques au mode source.

### Phase 4 — Interface graphique

- `scripts/gui.py` : interface PySide6 complète — carte de France (Leaflet embarqué
  localement, sans CDN, tuiles OpenStreetMap), synchronisation automatique entre carte,
  Lambert-93 et WGS84, saisie date/horaires avec « Journée entière », recherche des
  10 stations les plus proches avec disponibilité vérifiée en ligne, tableau de
  sélection avec présélection par défaut (stations disponibles les plus proches),
  téléchargement réel avec rapport, journal affichant tous les avertissements/erreurs.
- `app.ui.map_view` / `app.ui.map_bridge` : widget carte `QWebEngineView` + pont
  `QWebChannel` pour les événements carte -> Python (clic, glisser-déposer du marqueur,
  clic sur une station).
- `app.ui.workers` : threads Qt (`CatalogWorker`, `SearchWorker`, `DownloadWorker`)
  réutilisant telles quelles les fonctions déjà testées des phases 2-3, pour garder
  l'interface réactive pendant les échanges réseau.
- Corrige un rendu de carte totalement noir sur les postes sans accélération GPU
  (session distante/VM) via un repli en rendu logiciel QtWebEngine.
- Corrige l'absence des tuiles OpenStreetMap (page carte chargée depuis `file://`) :
  QtWebEngine bloque par défaut l'accès réseau distant depuis une origine locale
  (`LocalContentCanAccessRemoteUrls`), désormais activé explicitement.
- Validé par un test manuel de bout en bout (clic carte -> recherche réelle -> 10
  stations trouvées près de Brest -> présélection correcte en tenant compte des
  stations indisponibles -> activation du téléchargement).

### Phase 3 — Téléchargement réel

- `scripts/cli.py` (renommé depuis `prototype_cli.py`) : nouvelle option
  `--download DOSSIER` déclenchant le téléchargement effectif des fichiers
  disponibles/partiels vers `DOSSIER/RGP/AAAA-MM-JJ/STATION/`, avec décompression et
  conversion Hatanaka → RINEX, puis écriture du rapport `rapport_RGP.txt`.
- Module `app.rgp.report` : génération du rapport de téléchargement (cahier des
  charges §10), avec avertissements consolidés (données partielles, cadence
  alternative, fichier journalier de repli, erreurs de téléchargement).
- Vérification de l'espace disque disponible avant de lancer les téléchargements
  (`app.rgp.downloader.has_enough_disk_space`).
- Correction d'un bug de détection des fichiers Hatanaka : `Path.suffix` sur un nom
  RINEX 2 (`aaer257a.26d`) renvoie `.26d` et non `.d`, ce qui empêchait la conversion
  CRINEX → RINEX de se déclencher. Détection corrigée par expression régulière et
  validée par un téléchargement réel de bout en bout contre le serveur IGN.

### Phase 2 — Prototype fonctionnel

- Ajout du prototype en ligne de commande (`scripts/prototype_cli.py`) : saisie de la
  position du chantier (Lambert-93 ou WGS84), date, plage horaire ou journée entière ;
  recherche des stations RGP les plus proches ; vérification réelle de la disponibilité
  des fichiers RINEX ; affichage exact des fichiers qui seraient téléchargés.
- Module `app.geo.coordinates` : conversions Lambert-93 (EPSG:2154) <-> WGS84, et
  parsing des coordonnées sexagésimales du format IGS Site Log.
- Module `app.geo.distance` : distance géodésique (ellipsoïde WGS84).
- Module `app.rgp.provider_ign` : construction des chemins/URLs du serveur
  `rgpdata.ign.fr`, isolant toute connaissance spécifique à l'IGN.
- Module `app.rgp.catalog` : construction du catalogue des stations à partir des
  fiches de site IGS (`logsheet/*.log`), avec mise en cache locale (TTL configurable)
  et tolérance aux fiches mal formées (observées en conditions réelles sur le serveur
  IGN — signe sexagésimal omis, décimales manquantes, coordonnées aberrantes).
- Module `app.rgp.availability` : vérification par requête HTTP réelle (jamais une
  supposition), avec repli sur le fichier journalier quand les fichiers horaires sont
  incomplets, et suggestion de cadence alternative quand la cadence demandée est
  indisponible.
- Modules `app.rgp.downloader` et `app.rgp.rinex` : téléchargement réel et pipeline de
  décompression/conversion (`.Z`, `.gz`, Hatanaka via la bibliothèque `hatanaka`) —
  prêts pour le branchement en Phase 3, non encore appelés par le prototype (dry-run).
- Client HTTP (`app.utils.http_client`) avec retry/timeout, et validation des
  certificats via le magasin de confiance du système d'exploitation (`truststore`)
  pour fonctionner correctement derrière un proxy d'entreprise avec inspection TLS.
- Suite de tests (52 tests) reposant sur des fixtures locales reproduisant la
  structure réelle du serveur IGN — aucune dépendance au réseau pour les tests.

### Phase 1 — Analyse

- Documentation complète du fonctionnement réel du RGP IGN dans `docs/RGP_IGN.md`,
  établie par observation directe des serveurs (arborescence, nommage RINEX 2/3,
  cadences, granularité horaire/journalière, format des fiches de site, compression).
