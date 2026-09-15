# Fonctionnement réel du RGP IGN — Analyse (Phase 1)

> Document de référence pour l'implémentation du RGP Downloader Lahocy.
> Toutes les informations ci-dessous ont été **vérifiées par observation directe** des serveurs
> le 2026-09-15 (navigation HTTP réelle dans `rgpdata.ign.fr`, listing Apache `Index of /`).
> Le site documentaire `https://rgp.ign.fr` s'est montré **intermittent (503 Service Unavailable)**
> pendant l'analyse — ce qui confirme le principe directeur du projet : **ne pas dépendre de
> l'interface web IGN**, seulement du serveur de données brutes.

---

## 1. Serveurs

| Serveur | Rôle | État observé |
|---|---|---|
| `https://rgpdata.ign.fr` | Serveur HTTP de diffusion des données brutes (listing Apache "Index of /") | ✅ Stable, répond en HTTP simple, pas d'auth |
| `ftp://rgpdata.ign.fr` | Miroir FTP (anonymous / email) | Non testé (HTTP suffit et est plus simple à intégrer) |
| `ftp://rgpdata.ensg.eu` | Miroir FTP secondaire | Non testé |
| `https://rgp.ign.fr` | Site web / documentation / carte / service de calcul en ligne | ⚠️ Instable (503 par intermittence lors des tests) |

**Décision d'architecture : le téléchargeur n'utilisera QUE `https://rgpdata.ign.fr` en HTTP simple** (requêtes GET, pas d'auth, pas de session). C'est un serveur Apache statique (`Apache/2.4.68 (Debian)`) qui expose une arborescence de fichiers avec des pages d'index HTML standard.

- Fichier absent → **HTTP 404** classique (vérifié : requête sur une station/heure inexistante).
- Répertoire → page HTML `Index of /...` listant `<a href="...">` (nom, date de modif, taille).
- Aucune clé API, aucun token, aucun rate-limit détecté (mais on restera raisonnable : délais entre requêtes, cache local).

---

## 2. Arborescence réelle du serveur (`/pub/`)

Racine observée : `https://rgpdata.ign.fr/pub/`

```text
/pub/
├── data/              ← RINEX 2 (nom court), TOUJOURS à jour, inclut métropole + DOM-TOM
├── data_v2e/          ← Format RINEX2 "étendu" expérimental, ARRÊTÉ en 2017 (2011-2017 seulement)
├── data_v3/           ← RINEX 3 (nom long IGS), maintenu, avec un décalage de ~2 jours
├── gnss_mayotte/      ← Réseau spécifique Mayotte (REVOSIMA/volcanisme), HORS PÉRIMÈTRE v1
├── logsheet/          ← Fiches de site IGS (site logs) : 1 fichier .log par station, ~776 fichiers
├── products/          ← Produits calculés (coordonnées, éphémérides, troposphère...), pas des RINEX bruts
└── requetes/          ← Vide / inutilisé (legacy)
```

**Conséquence importante pour l'architecture** : `data_v2e` est un format mort, à ignorer totalement. Les deux flux réellement utiles sont **`data/`** (RINEX 2, disponibilité quasi temps réel) et **`data_v3/`** (RINEX 3, disponibilité avec un peu de retard, ~1-2 jours pour le fichier journalier). Le prototype ciblera **`data/` (RINEX 2)** en priorité car c'est le flux le plus rapidement disponible et le plus universellement lu par les logiciels de post-traitement topographique (TBC, Justin, etc.). Le support RINEX 3 (`data_v3/`) pourra être ajouté ensuite sans changer l'architecture (le provider expose déjà les deux).

### 2.1 `/pub/data/AAAA/JJJ/` (RINEX 2 — nom court)

```text
/pub/data/2026/257/
├── data_1/     ← cadence 1 Hz (1 seconde)
└── data_30/    ← cadence 30 secondes
```

- `AAAA` = année sur 4 chiffres.
- `JJJ` = jour de l'année (day-of-year, 001-366), **sur 3 chiffres, zéro-paddé**.
- Sous-répertoires observés : `data_1` et `data_30` uniquement (pas de `data_5` ni `data_15` constaté pour les jours inspectés — à ne pas supposer présent partout, vérifier dynamiquement).
- Les stations DOM-TOM (ex. `abd0` en Guadeloupe) sont **mélangées dans le même arbre** que les stations métropolitaines — pas d'arborescence séparée pour l'outre-mer dans `data/`.

**Nommage des fichiers RINEX 2** (convention IGS historique, confirmée par observation) :

```
ssssjjjh.aaT.Z
```

| Segment | Signification | Exemple |
|---|---|---|
| `ssss` | Code station 4 caractères (minuscules) | `aaer` |
| `jjj` | Jour de l'année, 3 chiffres | `257` |
| `h` | Code de session horaire : `a`-`x` = heures UTC 0-1h → 23-24h ; `0` (chiffre zéro) = **fichier journalier complet** | `a` (0h-1h UTC), `0` (jour entier) |
| `aa` | Année sur 2 chiffres | `26` |
| `T` | Type de fichier : `d` = observation compressée Hatanaka (CRINEX), `n` = navigation GPS, `g` = navigation GLONASS | `d`, `n`, `g` |
| `.Z` | Compression UNIX `compress` (LZW) | |

Exemples réels observés dans `/pub/data/2026/257/data_30/` :
- `aaer257a.26d.Z` — station AAER, jour 257/2026, heure a (0h-1h UTC), obs CRINEX 30s
- `aaer2570.26d.Z` — station AAER, jour 257/2026, **fichier journalier complet** (session `0`), 2.6 Mo (bien plus gros que les fichiers horaires)
- `aaer257a.26n.Z` — éphémérides GPS diffusées de la même heure
- `aaer257a.26g.Z` — éphémérides GLONASS diffusées

Le fichier journalier (session `0`) coexiste **dans le même répertoire** que les 24 fichiers horaires — ce n'est pas un répertoire séparé. Les deux cadences (`data_1` et `data_30`) suivent exactement la même convention de nom.

**Aucun fichier Galileo/BeiDou nav séparé n'a été observé en RINEX 2** (`.l`, `.q`, etc.) — cohérent avec le format RINEX 2.11 qui ne gère que GPS (`n`) et GLONASS (`g`) en fichiers de navigation distincts.

### 2.2 `/pub/data_v3/AAAA/JJJ/` (RINEX 3 — nom long IGS)

Même arborescence `AAAA/JJJ/data_1/` et `AAAA/JJJ/data_30/`, mais :
- Le flux RINEX 3 a un **décalage de mise à disposition** (au moment du test, le jour 257 n'était pas encore présent dans `data_v3`, seul le jour 255 l'était — soit ~2 jours de retard sur `data/`).
- Nommage long standard IGS :

```
SSSSMRCCC_S_AAAAJJJHHMM_PPP_FFF_DT.ext.gz
```

Exemples réels observés dans `/pub/data_v3/2026/255/data_30/` :
- `AAER00FRA_R_20262550000_01H_30S_MO.crx.gz` — obs horaire (01H), 30s, Hatanaka (crx), gzip
- `AAER00FRA_R_20262550000_01D_30S_MO.crx.gz` — obs **journalière** (01D), 30s
- `AAER00FRA_R_20262550000_01H_MN.rnx.gz` — navigation horaire **multi-constellations mixte** (MN = Mixed Nav), pas de séparation GPS/GLONASS comme en RINEX 2
- `AAER00FRA_R_20262550000_01D_MN.rnx.gz` — navigation journalière mixte

Décomposition : `AAER`(site 4c) `00`(monument) `FRA`(pays ISO) `_R_`(source=Receiver) `20262550000`(AAAA+JJJ+HHMM début) `_01H_`(période: 01H ou 01D) `30S_`(cadence) `MO`(type: MO=obs, MN=nav) `.crx`(Hatanaka RINEX3) ou `.rnx`(RINEX3 non compressé) `.gz`(gzip).

**Compression** : RINEX 2 → `.Z` (UNIX compress/LZW). RINEX 3 → `.gz` (gzip standard). Les deux formats utilisent Hatanaka (CRINEX, extension `d` en RINEX2 / `crx` en RINEX3) pour les fichiers d'observation.

### 2.3 `/pub/logsheet/` — métadonnées et coordonnées des stations

776 fichiers `.log` observés (un par station), nommés :

```
<id9>_<AAAAMMJJ>.log
```

Exemple : `aaer00fra_20251208.log` → identifiant 9 caractères `AAER00FRA` (= code 4 lettres `AAER` + monument `00` + code pays ISO3 `FRA`), daté de la dernière mise à jour de la fiche.

Le fichier suit le format standard **IGS Site Log v2.0** (texte). Champs clés extraits par test réel sur `AAER00FRA` :

```
Nine Character ID        : AAER00FRA
Site Name                : Aérodrome des Ardennes Etienne Riché
City or Town              : CHARLEVILLE-MEZIERES
Approximate Position (ITRF)
  X coordinate (m)       : 4112958.700
  Y coordinate (m)       : 334002.300
  Z coordinate (m)       : 4847353.400
  Latitude (N is +)      : +494656.88      ← format DDDMMSS.ss (sexagésimal), PAS décimal
  Longitude (E is +)     : +0043833.53
  Elevation (m,ellips.)  : 199.3
Receiver Type             : SEPT POLARX5
Satellite System          : GPS+GLO+GAL+BDS+SBAS
```

Points d'attention pour le parsing :
- La latitude/longitude est au format **DDDMMSS.ss** (ex. `+494656.88` = 49°46'56.88"), **pas en degrés décimaux** — conversion nécessaire.
- Les coordonnées ITRF (X/Y/Z) sont aussi fournies et peuvent servir de source alternative/vérification.
- Le champ **"Satellite System"** de la section récepteur en cours donne les constellations disponibles (GPS/GLO/GAL/BDS/SBAS...).
- Plusieurs sections `3.x` (historique récepteurs) et `4.x` (historique antennes) existent avec dates d'installation/retrait — utile pour savoir quel matériel était actif à une date donnée si besoin d'aller plus loin, mais pas nécessaire pour le MVP (seule la position du monument compte, elle ne change pas avec le matériel).
- Certaines stations DOM ont un code pays différent (`GLP` = Guadeloupe observé dans `abd000glp_...log`, `abmf00glp_...log`).

**Il n'existe pas de fichier catalogue unique consolidé** (type `stations.csv`) sur le serveur de données — le catalogue doit être **construit en agrégeant les 776 fiches individuelles**. C'est acceptable : ~776 fichiers texte de 10-20 Ko chacun (~10 Mo au total), téléchargeables une fois et **mis en cache localement** (cf. §14 du cahier des charges), avec bouton "Actualiser les stations RGP" pour re-télécharger.

*(Le site `rgp.ign.fr/STATIONS/` propose vraisemblablement une vue listée/carte équivalente, mais le site s'étant montré indisponible pendant l'analyse, on ne peut pas en garantir la structure — le provider IGN du projet n'en dépendra donc pas.)*

### 2.4 `/pub/products/` — produits calculés (hors périmètre RINEX brut)

Contient des solutions de coordonnées calculées (`coordinates/daily_*`, `hourly_*`, `weekly_*`), des éphémérides précises, troposphère, ionosphère. **Non utilisé pour le MVP** — ce sont des produits de post-traitement scientifique (séries temporelles de positions), pas les fichiers RINEX bruts qu'un topographe veut télécharger. À garder en tête pour de futures évolutions (ex. contrôle qualité).

---

## 3. Cadences et granularité temporelle

| Cadence | Répertoire | Format nom (RINEX2) |
|---|---|---|
| 1 seconde | `data_1/` | identique à `data_30/`, fichiers ~10x plus gros |
| 30 secondes | `data_30/` | voir §2.1 |

Aucune cadence intermédiaire (5s, 15s) n'a été constatée dans les répertoires inspectés. **Ne pas supposer leur existence** — le module `availability.py` doit vérifier dynamiquement (HEAD/GET) quelles cadences existent réellement pour une station/jour donnés plutôt que de les coder en dur.

## 4. Granularité des fichiers (horaire vs journalier)

- **Fichiers horaires** : session `a`-`x` (RINEX2) ou `01H` (RINEX3), un par heure UTC, disponibles avec une latence d'environ 1h-1h30 après la fin de l'heure (observé : fichier de l'heure `a` [0h-1h UTC] modifié à 01:03 UTC).
- **Fichier journalier** : session `0` (RINEX2) ou `01D` (RINEX3), disponible seulement après la fin de journée UTC complète (observé : fichier du jour 257 modifié à 03:05 UTC le lendemain).
- **Les deux coexistent** dans le même répertoire pour une cadence donnée — il faut donc, pour une plage horaire demandée par l'utilisateur :
  1. Essayer d'abord les fichiers horaires couvrant exactement la plage (moins de données à télécharger, conforme à la consigne §4 du cahier des charges) ;
  2. Si les fichiers horaires nécessaires n'existent pas mais que le fichier journalier existe, l'utiliser et **le signaler clairement** à l'utilisateur (rapport + avertissement UI), comme demandé.
- **Confirmation concrète (Phase 3)** : le fichier journalier n'est pas un simple renommage du dernier fichier horaire, c'est un fichier **réellement généré à part par un traitement côté IGN** — l'en-tête d'un fichier journalier réellement téléchargé (station AAER) contient `teqc 2019Feb25 IGN-RGP` dans les champs `PGM / RUN BY / DATE` et `COMMENT`, montrant que l'IGN utilise l'outil `teqc` (UNAVCO) pour **concaténer les 24 fichiers horaires d'une même station en un seul fichier journalier**, produit après la fin de la journée UTC (cohérent avec l'horodatage observé, ~03:05 UTC le lendemain, très postérieur aux fichiers horaires eux-mêmes). C'est exactement le fichier que `check_availability()` (`app/rgp/availability.py`) utilise en repli.
- Toutes les heures sont **en UTC**. L'IGN ne publie pas d'heure locale — l'application devra convertir l'heure locale (chantier en France métropolitaine ou DOM-TOM) saisie par l'utilisateur vers UTC avant de déterminer les fichiers/sessions horaires à cibler (attention aux fuseaux DOM-TOM et à l'heure d'été/hiver en métropole).

## 5. Disponibilité réelle des données

Il n'existe **aucune API de disponibilité** — la seule façon fiable de savoir si un fichier existe est de faire une requête HTTP (HEAD ou GET) sur son URL exacte et d'observer le code de retour :
- **200** → fichier disponible, taille connue via `Content-Length`.
- **404** → fichier absent (station arrêtée ce jour-là, panne, pas encore livré, cadence non déployée sur cette station...).

Il n'y a pas de distinction serveur entre "jamais eu de données" et "pas encore livré aujourd'hui" — l'application doit interpréter le contexte (date future/passée récente vs ancienne) pour formuler un message pertinent à l'utilisateur (cf. §11 du cahier des charges : messages compréhensibles).

## 6. Formats et compression — outils de traitement

| Élément | Constat |
|---|---|
| RINEX 2 obs | Hatanaka (CRINEX), extension `d`, compressé `.Z` |
| RINEX 2 nav | Non compressé Hatanaka (c'est déjà un format texte compact), extensions `n` (GPS)/`g` (GLONASS), compressé `.Z` |
| RINEX 3 obs | Hatanaka (CRINEX3), extension `.crx`, compressé `.gz` |
| RINEX 3 nav | Non-Hatanaka, extension `.rnx`, mixte multi-GNSS, compressé `.gz` |
| Compression `.Z` | Format UNIX `compress` (LZW), **pas géré nativement par le module `gzip` de Python** |
| Compression `.gz` | gzip standard, géré par le module `gzip` de la stdlib Python |
| Décompression Hatanaka | Format binaire spécifique (RNXCMP de Y. Hatanaka / GSI Japon), **ne pas réimplémenter** |

**Outils recommandés (ne pas réinventer)** :
- Décompression `.Z` : bibliothèque Python pure `unlzw3` (MIT), pas de dépendance binaire.
- Décompression `.gz` : module standard `gzip`.
- Conversion CRINEX → RINEX (Hatanaka) : bibliothèque Python `hatanaka` (wrapper autour des exécutables officiels **RNXCMP** de Y. Hatanaka/GSI, distribués avec l'accord officiel IGS/GSI, multiplateforme dont Windows) — évite de réimplémenter l'algorithme et évite de gérer manuellement un binaire externe. Alternative : appeler directement les binaires `CRX2RNX` officiels si on préfère éviter une dépendance Python supplémentaire.

Ce choix confirme la consigne du cahier des charges (§9) : *"Ne pas réimplémenter un décodeur Hatanaka complexe si une bibliothèque ou un outil fiable existe."*

## 7. Comportement en cas de données absentes

- Fichier non trouvé → HTTP 404, pas de redirection, pas de page d'erreur JSON — juste la page 404 Apache standard.
- Il n'y a pas de "placeholder" ni de fichier vide : soit le fichier existe avec des données, soit il n'existe pas du tout.
- Pas de moyen serveur de distinguer "station hors service définitivement" de "panne temporaire" — seule l'historique (logsheet mentionne une éventuelle date de démontage dans une future section "Sites presently not in operation" si l'IGN la maintient) peut donner un indice, mais ce n'est pas fiable à 100 % et ne sera pas utilisé pour bloquer une tentative de téléchargement — l'app essaiera toujours en direct et rapportera le résultat réel.

## 8. Constellations GNSS disponibles

Information disponible **par station** dans la fiche de site (`logsheet`), champ "Satellite System" de la section récepteur active (ex. `GPS+GLO+GAL+BDS+SBAS`). Ce n'est donc pas une caractéristique du réseau entier mais **du matériel installé à chaque station**, qui peut évoluer dans le temps. Pour le MVP, on affichera la valeur de la configuration récepteur la plus récente de la fiche.

En pratique, la présence de fichiers navigation GPS (`n`)/GLONASS (`g`) en RINEX2 ne renseigne que sur GPS+GLONASS (RINEX 2.11 ne distingue pas plus) ; le fichier `MN` mixte en RINEX3 contient potentiellement toutes les constellations reçues par le récepteur (GPS/GLONASS/Galileo/BeiDou/SBAS) sans avoir besoin de fichiers séparés.

### 8.1 Fusion des fichiers horaires et filtrage par constellation (fonctionnalité applicative)

L'application propose de fusionner plusieurs fichiers horaires d'une même station/journée en un seul fichier RINEX continu couvrant exactement la période demandée, avec filtrage optionnel par constellation (`app/rgp/rinex_merge.py`) — un besoin exprimé après coup, inspiré d'un ancien service en ligne de l'IGN qui faisait ce travail côté serveur.

Deux outils de référence du domaine ont été évalués et écartés :
- **gfzrnx** (GFZ Potsdam) : le plus complet et activement maintenu, mais sa licence impose un abonnement commercial (~300 €/an) pour un usage professionnel routinier — incompatible avec un usage Lahocy sans validation budgétaire préalable.
- **teqc** (UNAVCO) : gratuit pour tout usage, et très probablement l'outil utilisé par l'ancien service IGN (on a observé la signature `teqc 2019Feb25 IGN-RGP` dans l'en-tête d'un fichier journalier réel, §4) — mais non maintenu depuis 2019.

Faute d'outil librement redistribuable et maintenu, un fusionneur RINEX 2 maison a été écrit (`app/rgp/rinex_merge.py`), à portée volontairement limitée : il ne traite que le cas réellement rencontré ici (fichiers de la même station/même journée, donc en-têtes identiques), pas la fusion RINEX générique. Format vérifié contre la spec officielle RINEX 2.11 (files.igs.org/pub/data/format/rinex211.txt) et validé sur des données RGP réelles (fichier à 26 types d'observation, époques jusqu'à 36 satellites multi-constellations nécessitant plusieurs lignes de continuation).

## 9. Réseau et zones couvertes

- Réseau principal métropole + DOM (Guadeloupe `GLP`, etc.) mélangés dans `/pub/data/`.
- Réseau spécifique Mayotte (`/pub/gnss_mayotte/`) : structure différente (`calculs/`, `produits/`, `stations/`), lié au dispositif de surveillance volcanique REVOSIMA — **hors périmètre v1**, à traiter comme un "autre fournisseur" potentiel plus tard (cf. §19 évolutions futures du cahier des charges, "autres fournisseurs").

---

## 10. Conséquences directement actionnables pour l'architecture (`rgp/provider_ign.py`)

1. **Base URL unique et configurable** : `https://rgpdata.ign.fr/pub` (dans `config.yaml`, jamais codée en dur ailleurs).
2. **Construction de chemin RINEX2** : `data/{YYYY}/{DDD:03d}/data_{cadence}/{station}{DDD:03d}{hour_code}.{YY}{type}.Z`.
3. **Construction de chemin RINEX3** : `data_v3/{YYYY}/{DDD:03d}/data_{cadence}/{STATION9}_R_{YYYY}{DDD:03d}{HHMM}_{period}_{cadence}S_{MO|MN}.{crx|rnx}.gz`.
4. **Vérification de disponibilité = requête HTTP réelle (HEAD)** par fichier candidat, jamais une supposition basée sur le catalogue de stations.
5. **Catalogue de stations = agrégation des 776 fiches `logsheet/*.log`**, mis en cache local (JSON/SQLite), avec conversion des coordonnées sexagésimales → décimal WGS84 dès le parsing.
6. **Sélection horaire → sessions** : convertir l'heure locale utilisateur en UTC, déterminer la liste des lettres de session (`a`-`x`) couvrant `[début, fin]`, tenter ces fichiers horaires en premier, sinon fallback sur le fichier journalier (`0`/`01D`) avec avertissement.
7. **Aucune dépendance à `rgp.ign.fr`** (site web, service de calcul en ligne) — confirmé indispensable car ce site s'est montré instable (503) durant l'analyse elle-même.
8. **Isolation totale dans `provider_ign.py`** : si l'IGN change un jour son arborescence ou ses extensions, seul ce module (+ `config.yaml`) est à adapter.

---

## 11. Points restant à surveiller / non garantis à 100 %

- Le comportement exact de la disponibilité RINEX3 (`data_v3`) pour des cadences autres que 1s/30s n'a pas été testé sur d'autres jours/stations — à revérifier dynamiquement, jamais supposé.
- Le site `rgp.ign.fr` (documentation officielle, page "Format des données", "Type de données", liste des stations) était indisponible (503) pendant toute la session d'analyse ; les informations qu'il contient n'ont donc pas pu être croisées. Les faits ci-dessus reposent uniquement sur l'observation directe du serveur de données réel, ce qui est conforme à la consigne du projet ("ne pas dépendre de l'interface graphique"), mais il serait utile de revalider certains points (latence exacte de publication, historique de rétention) quand le site sera de nouveau accessible.
- Le FTP (`ftp://rgpdata.ign.fr`) n'a pas été testé — le HTTP suffit et est plus simple/robuste à intégrer (pas de gestion de session FTP), donc non prioritaire.
