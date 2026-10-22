# Onglet « Stations de référence » — sources de données vérifiées

Comme pour le RGP (voir `RGP_IGN.md`), rien n'est supposé : tout ce qui suit a été
observé directement le 2026-10-22.

## Réseaux proposés

| Réseau | Source des positions | Volume observé |
|---|---|---|
| RGP (IGN) | catalogue des fiches de site déjà construit (`RGP_IGN.md` §2.3) | ~766 antennes |
| Centipède RTK | table des mounts (sourcetable) du caster NTRIP | 1304 mounts, ~1301 exploitables |

Un autre caster NTRIP 2.0 public s'ajoute dans `config/config.yaml`
(`reference_networks.ntrip_casters`), sans modifier le code.

## Centipède : comment lister les antennes

- Caster documenté : hôte `crtk.net` (alias `caster.centipede.fr`), port **2101** (NTRIP en
  clair) et port **443** (NTRIP 2.0 sur TLS) — <https://docs.centipede-rtk.org/access.html>.
- **Le port 2101 est filtré sur le réseau de développement** (DNS correct, TCP refusé ;
  80 et 443 répondent). L'appli lit donc la table via **`GET https://crtk.net/`** avec l'en-tête
  `Ntrip-Version: Ntrip/2.0` : réponse HTTP 200 `text/plain`, ~280 Ko.
- La carte publique (Lizmap `map.centipede-rtk.org`) n'a **pas** été retenue comme source : elle
  renvoyait un `502 Bad Gateway` pendant l'analyse, et ses endpoints WFS ne sont pas documentés.
- Format d'une ligne `STR` (19 champs, vérifié sur les 1304 lignes) :
  `STR;mount;identifiant;format;détails;porteuse;systèmes GNSS;réseau;pays;lat;lon;nmea;solution;générateur;compression;auth;frais;débit;divers`.
  - Latitude/longitude en degrés décimaux WGS84, champs 9 et 10.
  - Le champ « réseau » vaut `NONE` pour 1279 mounts (sous-réseau dans « divers », ex.
    `CentipedeRTK`) et `RENAG` pour 25.
  - Plusieurs bases n'ont pour « identifiant » que leur code pays (`FRA`) : traité comme « sans nom ».
- Les mounts `NEAR` et `NEAR4` sont des mounts **virtuels** (« base la plus proche », positionnés
  arbitrairement en 46.000, -1.213) : exclus (`virtual_mounts` dans la config).
- Robustesse : la liste est mise en cache (`ntrip_cache_ttl_days`) ; si le caster est injoignable,
  la dernière liste connue est utilisée **avec un avertissement explicite** plutôt que de laisser
  la carte vide.

## Adresse → position

Géocodeur IGN Géoplateforme (données BAN) :
`GET https://data.geopf.fr/geocodage/search?q=<adresse>&limit=<n>` → FeatureCollection GeoJSON,
coordonnées `[lon, lat]` WGS84, `properties.label` et `properties.score`. URL configurable.
Exemple : « 12 rue de Paris, Rennes » → 48.112112, -1.669676 (score 0.98).

## Limites connues

- Les positions sont celles déclarées par chaque réseau (précision décimétrique à métrique selon
  la source) : suffisant pour choisir une antenne, pas pour du positionnement.
- Être listée dans la table des mounts **n'est pas vérifié comme garantissant qu'une base émet
  réellement des corrections en ce moment** : l'appli ne teste pas l'état en direct d'une base
  (non vérifié sur ce caster). Pour un usage terrain, contrôler l'état sur la carte du réseau.
