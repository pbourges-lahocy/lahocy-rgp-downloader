# Changelog

Toutes les modifications notables de ce projet sont documentées ici.

## [0.3.0] - 2026-10-22

- **Onglet « Stations de référence »** : carte des antennes RGP et Centipède RTK avec choix
  des réseaux, recherche par adresse (géocodeur IGN Géoplateforme) ou clic sur la carte, liste
  des antennes les plus proches, reprise de la position dans l'onglet de téléchargement.
  - Nouveau package `app.refstations` (lecture des sourcetables NTRIP 2.0 en HTTPS port 443 —
    le port 2101 est filtré sur le réseau de développement —, cache avec repli sur la dernière
    liste connue si le caster est en panne, géocodage, plus proches voisins).
  - Réseaux et URL dans `config.yaml` (`reference_networks`) ; un caster NTRIP 2.0 s'ajoute sans code.
  - Chargement parallèle (un thread par réseau) pour qu'un réseau lent ou en panne ne bloque pas l'autre.
  - `docs/REFERENCE_STATIONS.md` : sources vérifiées (1304 mounts Centipède, mounts virtuels
    exclus, carte Lizmap en 502 pendant l'analyse).
  - `RgpHttpClient.get_text` accepte des en-têtes par requête ; messages d'erreur génériques.
  - **État actif / inactif** : pas de champ dédié dans les données (ni Centipède ni RGP). Centipède :
    une base du caster n'est servie dans la table que si elle est connectée (règle lue dans le code
    du caster Millipede) ; les 26 bases fédérées RENAG restent « inconnues » ; une base déjà vue
    puis absente apparaît « hors ligne, dernière vue le… » grâce à un historique local ; caster
    injoignable = tous états « inconnus ». RGP : activité mesurée sur la publication du dernier
    fichier horaire (`app.refstations.rgp_activity`) ; « inactif » inclut les nombreuses stations du
    catalogue non diffusées publiquement, ce qui est précisé dans la fiche de l'antenne.
  - **Étiquettes** avec le nom de chaque antenne sur la carte, anneau vert/rouge/blanc selon l'état,
    colonne « État » et option « Exclure les antennes inactives du classement ».
  - Cache Centipède ramené à 15 minutes (l'état doit rester frais).
  - 26 tests pour le package `refstations`.

## [0.2.0] - 2026-09-15

- Cadence par défaut passée de 30s à 1s (`config/config.yaml`).
- Documentation de l'avertissement Microsoft Defender SmartScreen au lancement de
  l'exécutable non signé (contournement `Unblock-File` sans droits admin, pistes de
  distribution durable à arbitrer plus tard) — voir README.
- **Fusion des fichiers RINEX horaires et filtrage par constellation** :
  - `app/rgp/rinex_merge.py` : fusionne plusieurs fichiers RINEX 2 horaires d'une même
    station/journée en un seul fichier continu couvrant exactement la période demandée,
    avec filtrage optionnel par constellation GNSS (GPS/GLONASS/Galileo/BeiDou/SBAS).
    Portée volontairement limitée à ce cas précis (en-têtes identiques) plutôt qu'un
    outil de fusion RINEX générique — gfzrnx (payant en usage professionnel routinier,
    ~300 €/an) et teqc (non maintenu depuis 2019) ont été écartés ; voir
    docs/RGP_IGN.md §8.1. Format vérifié contre la spec RINEX 2.11 officielle et
    validé sur des données RGP réelles (26 types d'observation, époques à 36
    satellites multi-constellations avec lignes de continuation).
  - `app/rgp/downloader.py` : `download_and_merge_station_files()` orchestre
    téléchargement + fusion, avec nommage explicite du fichier résultant
    (`STATIONjjj_HHMM-HHMM[_LETTRES].yyo`) et repli sûr sur les fichiers individuels
    si la fusion échoue (jamais de perte de données).
  - CLI : nouvelle option `--constellations G,R,E,...`.
  - Interface graphique : cases à cocher par constellation dans le panneau
    Téléchargement (tout coché par défaut = aucun filtrage).
  - `app/rgp/report.py` : le rapport indique le fichier fusionné et les constellations
    conservées.
  - 13 nouveaux tests (dont validation réelle contre le serveur IGN).

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
