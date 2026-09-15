"""Générateurs de fixtures RINEX2 valides, partagés entre plusieurs modules de tests.

Positions de colonnes vérifiées contre la spec RINEX 2.11 officielle
(files.igs.org/pub/data/format/rinex211.txt, table A2) — voir app.rgp.rinex_merge.
"""

from pathlib import Path

END_OF_HEADER = "END OF HEADER"
OBS_TYPES_LABEL = "# / TYPES OF OBSERV"


def header_line(content: str, label: str) -> str:
    line = f"{content:<60}{label:<20}"
    assert len(line) == 80
    return line


def obs_types_header(types: list[str]) -> list[str]:
    lines = []
    count = len(types)
    batch, rest = types[:9], types[9:]
    content = f"{count:6d}" + "".join(f"{t:>6}" for t in batch)
    lines.append(header_line(content, OBS_TYPES_LABEL))
    while rest:
        batch, rest = rest[:9], rest[9:]
        content = " " * 6 + "".join(f"{t:>6}" for t in batch)
        lines.append(header_line(content, OBS_TYPES_LABEL))
    return lines


def make_header(types: list[str]) -> list[str]:
    lines = [
        header_line("     2.11           OBSERVATION DATA    M (MIXED)", "RINEX VERSION / TYPE"),
        header_line("AAER", "MARKER NAME"),
    ]
    lines.extend(obs_types_header(types))
    lines.append(header_line("", END_OF_HEADER))
    return lines


def epoch_prefix(year: int, month: int, day: int, hour: int, minute: int, sec: float, flag: int, num_records: int) -> str:
    prefix = (
        " "
        + f"{year % 100:02d}"
        + f" {month:2d}"
        + f" {day:2d}"
        + f" {hour:2d}"
        + f" {minute:2d}"
        + f"{sec:11.7f}"
        + "  "
        + f"{flag:1d}"
        + f"{num_records:3d}"
    )
    assert len(prefix) == 32
    return prefix


def epoch_lines(year, month, day, hour, minute, sec, satellites: list[str]) -> list[str]:
    prefix = epoch_prefix(year, month, day, hour, minute, sec, 0, len(satellites))
    lines = []
    remaining = list(satellites)
    first = True
    while remaining or first:
        chunk, remaining = remaining[:12], remaining[12:]
        codes = "".join(f"{s[0]}{s[1:]:>2}" for s in chunk)
        line_prefix = prefix if first else " " * 32
        lines.append(f"{line_prefix}{codes}")
        first = False
    return lines


def obs_value_lines(num_obs_types: int, satellites: list[str], base_value: float = 100.0) -> list[str]:
    """Génère des lignes d'observation factices (valeurs croissantes), 5 par ligne max."""
    lines = []
    for si, _sat in enumerate(satellites):
        values = [f"{base_value + si + k:14.3f}00" for k in range(num_obs_types)]
        for i in range(0, len(values), 5):
            lines.append("".join(values[i : i + 5]))
    return lines


def build_rinex_file(tmp_path: Path, name: str, types: list[str], epochs: list[tuple]) -> Path:
    """epochs: liste de (y,m,d,h,mi,s,satellites)."""
    lines = make_header(types)
    for y, m, d, h, mi, s, sats in epochs:
        lines.extend(epoch_lines(y, m, d, h, mi, s, sats))
        lines.extend(obs_value_lines(len(types), sats))
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


def build_rinex_text(types: list[str], epochs: list[tuple]) -> str:
    """Comme build_rinex_file, mais retourne le texte sans l'écrire sur disque."""
    lines = make_header(types)
    for y, m, d, h, mi, s, sats in epochs:
        lines.extend(epoch_lines(y, m, d, h, mi, s, sats))
        lines.extend(obs_value_lines(len(types), sats))
    return "\n".join(lines) + "\n"
