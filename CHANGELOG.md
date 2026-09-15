# Changelog

Toutes les modifications notables de ce projet sont documentées ici.

## [Non publié]

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
