"""Fusion et filtrage par constellation de fichiers RINEX 2 observation.

Combine plusieurs fichiers horaires d'une même station / même journée (donc
avec un en-tête identique : même récepteur, mêmes types d'observation) en un
seul fichier RINEX continu couvrant exactement la période demandée, avec un
filtrage optionnel par constellation GNSS.

Portée volontairement restreinte à ce cas précis rencontré par ce projet —
ce n'est PAS un outil de fusion RINEX générique. Les outils de référence du
domaine (gfzrnx, teqc) ont été écartés : gfzrnx impose une licence payante
pour un usage professionnel routinier (~300 €/an), et teqc n'est plus
maintenu depuis 2019 par UNAVCO — voir docs/RGP_IGN.md. Comme les fichiers
d'entrée proviennent tous de la même station pour la même journée, leurs
en-têtes sont identiques, ce qui rend la fusion nettement plus simple que le
cas général qu'adressent ces outils.

Format RINEX 2.11 utilisé ici (colonnes 1-indexées, voir spec officielle) :
- Ligne d'époque : année(I2) mois(I2) jour(I2) heure(I2) min(I2) sec(F11.7)
  flag(I1) nbSat(I3) puis jusqu'à 12 satellites en (A1,I2), continué sur une
  ou plusieurs lignes si plus de 12 satellites (colonnes 1-32 alors vides).
- Chaque satellite est suivi d'autant de lignes que nécessaire pour lister
  ses observations, à raison de 5 valeurs (F14.3 + 2 flags) par ligne — le
  nombre de lignes par satellite dépend du nombre de types d'observation
  déclarés dans l'en-tête ("# / TYPES OF OBSERV").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

END_OF_HEADER = "END OF HEADER"
OBS_TYPES_LABEL = "# / TYPES OF OBSERV"

# Lettre de système RINEX -> nom lisible (constellations couramment rencontrées au RGP).
GNSS_SYSTEMS: dict[str, str] = {
    "G": "GPS",
    "R": "GLONASS",
    "E": "Galileo",
    "C": "BeiDou",
    "S": "SBAS",
    "J": "QZSS",
    "I": "IRNSS",
}


class RinexMergeError(RuntimeError):
    """La fusion a été refusée plutôt que de risquer de produire un fichier corrompu."""


@dataclass
class _Epoch:
    header_lines: list[str]
    flag: int
    satellites: list[str]  # ex. ["G16", "R03", ...], vide si flag spécial (>=2)
    sat_obs_lines: dict[str, list[str]]  # satellite -> lignes d'observation brutes
    special_lines: list[str] = field(default_factory=list)  # contenu brut si flag >= 2


def _read_lines(path: Path) -> list[str]:
    # Les fichiers RINEX du RGP sont en ASCII pur ; on tolère un éventuel Latin-1
    # résiduel comme pour les fiches logsheet (voir app.utils.http_client).
    try:
        return path.read_text(encoding="ascii").splitlines()
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1").splitlines()


def _split_header_body(lines: list[str]) -> tuple[list[str], list[str]]:
    for i, line in enumerate(lines):
        if line[60:80].strip() == END_OF_HEADER:
            return lines[: i + 1], lines[i + 1 :]
    raise RinexMergeError("Fichier RINEX sans ligne 'END OF HEADER' — fichier probablement corrompu.")


def _extract_obs_types(header_lines: list[str]) -> list[str]:
    types: list[str] = []
    count_declared: int | None = None
    for line in header_lines:
        if line[60:80].strip() != OBS_TYPES_LABEL:
            continue
        content = line[:60]
        if count_declared is None:
            count_declared = int(content[:6])
            content = content[6:]
        codes = [content[i : i + 6].strip() for i in range(0, len(content), 6)]
        types.extend(c for c in codes if c)
    if count_declared is not None and len(types) != count_declared:
        raise RinexMergeError(
            f"En-tête RINEX incohérent : {count_declared} types d'observation annoncés, {len(types)} lus."
        )
    return types


def _obs_lines_per_satellite(num_obs_types: int) -> int:
    return max(1, math.ceil(num_obs_types / 5))


def _headers_compatible(reference: list[str], other: list[str]) -> bool:
    return _extract_obs_types(reference) == _extract_obs_types(other)


def _parse_epoch_header(first_line: str) -> tuple[int, int]:
    """Retourne (flag, nombre de satellites/enregistrements) depuis la 1ère ligne d'époque."""
    flag = int(first_line[28:29])
    n = int(first_line[29:32])
    return flag, n


def _parse_satellite_list(epoch_lines: list[str]) -> list[str]:
    satellites: list[str] = []
    joined = "".join(line[32:68] for line in epoch_lines)
    for i in range(0, len(joined), 3):
        code = joined[i : i + 3].strip()
        if code:
            # Certains récepteurs omettent la lettre système pour le GPS ('G' implicite).
            satellites.append(code if not code[0].isdigit() else f"G{code}")
    return satellites


def _iter_epochs(body_lines: list[str], lines_per_sat: int) -> list[_Epoch]:
    epochs: list[_Epoch] = []
    i = 0
    n = len(body_lines)
    while i < n:
        first_line = body_lines[i]
        if not first_line.strip():
            i += 1
            continue
        flag, count = _parse_epoch_header(first_line)

        header_lines = [first_line]
        i += 1
        if flag in (0, 1):
            # Lignes de continuation de la liste de satellites si plus de 12.
            remaining_sats = count - 12
            while remaining_sats > 0:
                header_lines.append(body_lines[i])
                i += 1
                remaining_sats -= 12

            satellites = _parse_satellite_list(header_lines)
            sat_obs_lines: dict[str, list[str]] = {}
            for sat in satellites:
                sat_obs_lines[sat] = body_lines[i : i + lines_per_sat]
                i += lines_per_sat

            epochs.append(_Epoch(header_lines=header_lines, flag=flag, satellites=satellites, sat_obs_lines=sat_obs_lines))
        else:
            # Époque spéciale (événement, en-tête additionnel...) : on la recopie telle
            # quelle sans tenter de l'interpréter, `count` donne le nombre de lignes suivantes.
            special_lines = body_lines[i : i + count]
            i += count
            epochs.append(_Epoch(header_lines=header_lines, flag=flag, satellites=[], sat_obs_lines={}, special_lines=special_lines))

    return epochs


def _format_epoch(epoch: _Epoch, keep_systems: set[str] | None) -> list[str] | None:
    if epoch.flag not in (0, 1) or keep_systems is None:
        return epoch.header_lines + [line for lines in epoch.sat_obs_lines.values() for line in lines] + epoch.special_lines

    kept = [sat for sat in epoch.satellites if sat[0] in keep_systems]
    if not kept:
        return None  # époque entièrement filtrée : on ne l'écrit pas

    sat_codes = "".join(f"{sat[0]}{sat[1:]:>2}" for sat in kept)
    # Reconstruit la/les ligne(s) d'en-tête d'époque avec la liste de satellites filtrée,
    # en conservant tel quel le préfixe horodatage+flag (colonnes 1-32) de la 1ère ligne.
    prefix = epoch.header_lines[0][:29] + f"{len(kept):3d}"
    new_header_lines: list[str] = []
    remaining = sat_codes
    first = True
    while remaining or first:
        chunk, remaining = remaining[:36], remaining[36:]
        line_prefix = prefix if first else " " * 32
        new_header_lines.append(f"{line_prefix}{chunk}")
        first = False

    obs_lines = [line for sat in kept for line in epoch.sat_obs_lines[sat]]
    return new_header_lines + obs_lines


def merge_rinex2_observation_files(
    paths: list[Path], output_path: Path, keep_systems: set[str] | None = None
) -> Path:
    """Fusionne (et filtre optionnellement par constellation) des fichiers RINEX 2 obs.

    `paths` doit contenir des fichiers de la MÊME station et de la MÊME journée,
    déjà décompressés/convertis (RINEX observation, pas CRINEX), triés chronologiquement.
    `keep_systems` : ensemble de lettres système RINEX à conserver (ex. {"G", "E"}),
    ou None pour ne filtrer aucune constellation.
    """
    if not paths:
        raise RinexMergeError("Aucun fichier à fusionner.")

    all_lines = [_read_lines(p) for p in paths]
    headers, bodies = zip(*(_split_header_body(lines) for lines in all_lines))

    reference_header = headers[0]
    for path, header in zip(paths[1:], headers[1:]):
        if not _headers_compatible(reference_header, header):
            raise RinexMergeError(
                f"Impossible de fusionner {paths[0].name} et {path.name} : "
                "types d'observation différents (stations ou configurations différentes)."
            )

    obs_types = _extract_obs_types(reference_header)
    lines_per_sat = _obs_lines_per_satellite(len(obs_types))

    output_lines = list(reference_header)
    for body in bodies:
        for epoch in _iter_epochs(body, lines_per_sat):
            formatted = _format_epoch(epoch, keep_systems)
            if formatted is not None:
                output_lines.extend(formatted)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(output_lines) + "\n", encoding="ascii")
    return output_path
