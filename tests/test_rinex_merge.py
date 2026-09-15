"""Tests du fusionneur RINEX2 maison, contre le format RINEX 2.11 officiel.

Les positions de colonnes utilisées ici sont vérifiées contre la spec RINEX 2.11
(files.igs.org/pub/data/format/rinex211.txt, table A2) : ligne d'époque en
1X,I2.2,4(1X,I2),F11.7,2X,I1,I3,12(A1,I2) — flag en colonne 29, nombre de
satellites en colonnes 30-32, liste des satellites en colonnes 33-68.
"""

from pathlib import Path

import pytest

from app.rgp.rinex_merge import RinexMergeError, merge_rinex2_observation_files
from tests.rinex_fixtures import build_rinex_file


def read_epoch_summaries(path: Path) -> list[tuple[int, list[str]]]:
    """Relit un fichier RINEX produit et retourne [(numsat, [satellites]), ...] par époque."""
    from app.rgp.rinex_merge import _extract_obs_types, _iter_epochs, _obs_lines_per_satellite, _split_header_body

    lines = path.read_text(encoding="ascii").splitlines()
    header, body = _split_header_body(lines)
    types = _extract_obs_types(header)
    epochs = _iter_epochs(body, _obs_lines_per_satellite(len(types)))
    return [(len(e.satellites), e.satellites) for e in epochs]


TYPES_2 = ["L1", "C1"]


def test_concatenate_two_files_without_filter(tmp_path):
    file1 = build_rinex_file(
        tmp_path, "h1.26o", TYPES_2,
        [(2026, 9, 14, 8, 0, 0.0, ["G01", "G02"]), (2026, 9, 14, 8, 30, 0.0, ["G01", "R03"])],
    )
    file2 = build_rinex_file(
        tmp_path, "h2.26o", TYPES_2,
        [(2026, 9, 14, 9, 0, 0.0, ["G01", "G02", "R03"])],
    )

    output = merge_rinex2_observation_files([file1, file2], tmp_path / "merged.26o")

    summaries = read_epoch_summaries(output)
    assert [count for count, _ in summaries] == [2, 2, 3]
    assert summaries[2][1] == ["G01", "G02", "R03"]


def test_filter_keeps_only_selected_constellation(tmp_path):
    file1 = build_rinex_file(
        tmp_path, "h1.26o", TYPES_2,
        [(2026, 9, 14, 8, 0, 0.0, ["G01", "R03", "G02"])],
    )

    output = merge_rinex2_observation_files([file1], tmp_path / "merged.26o", keep_systems={"G"})

    summaries = read_epoch_summaries(output)
    assert summaries == [(2, ["G01", "G02"])]


def test_filter_drops_epoch_left_with_no_satellites(tmp_path):
    file1 = build_rinex_file(
        tmp_path, "h1.26o", TYPES_2,
        [
            (2026, 9, 14, 8, 0, 0.0, ["R03"]),  # uniquement GLONASS -> disparaît si on ne garde que G
            (2026, 9, 14, 8, 30, 0.0, ["G01"]),
        ],
    )

    output = merge_rinex2_observation_files([file1], tmp_path / "merged.26o", keep_systems={"G"})

    summaries = read_epoch_summaries(output)
    assert summaries == [(1, ["G01"])]


def test_satellite_list_continuation_over_12_satellites(tmp_path):
    satellites = [f"G{i:02d}" for i in range(1, 14)]  # 13 satellites -> ligne de continuation
    file1 = build_rinex_file(tmp_path, "h1.26o", TYPES_2, [(2026, 9, 14, 8, 0, 0.0, satellites)])

    output = merge_rinex2_observation_files([file1], tmp_path / "merged.26o")

    summaries = read_epoch_summaries(output)
    assert summaries == [(13, satellites)]


def test_satellite_list_continuation_preserved_after_filtering(tmp_path):
    # 13 GPS + 2 GLONASS ; filtrer sur GPS doit garder la continuation (13 > 12).
    satellites = [f"G{i:02d}" for i in range(1, 14)] + ["R01", "R02"]
    file1 = build_rinex_file(tmp_path, "h1.26o", TYPES_2, [(2026, 9, 14, 8, 0, 0.0, satellites)])

    output = merge_rinex2_observation_files([file1], tmp_path / "merged.26o", keep_systems={"G"})

    summaries = read_epoch_summaries(output)
    assert summaries == [(13, [f"G{i:02d}" for i in range(1, 14)])]


def test_multiline_observations_when_more_than_five_types(tmp_path):
    types = ["L1", "L2", "C1", "C2", "P1", "P2", "D1"]  # 7 types -> 2 lignes par satellite
    file1 = build_rinex_file(tmp_path, "h1.26o", types, [(2026, 9, 14, 8, 0, 0.0, ["G01", "R03"])])

    output = merge_rinex2_observation_files([file1], tmp_path / "merged.26o", keep_systems={"R"})

    summaries = read_epoch_summaries(output)
    assert summaries == [(1, ["R03"])]
    # Vérifie que les 2 lignes d'observation du satellite conservé sont bien présentes,
    # et qu'aucune ligne du satellite G01 filtré ne traîne dans le fichier.
    output_lines = output.read_text(encoding="ascii").splitlines()
    obs_lines = output_lines[-2:]
    assert len(obs_lines) == 2


def test_rejects_files_with_incompatible_observation_types(tmp_path):
    file1 = build_rinex_file(tmp_path, "h1.26o", ["L1", "C1"], [(2026, 9, 14, 8, 0, 0.0, ["G01"])])
    file2 = build_rinex_file(tmp_path, "h2.26o", ["L1", "C1", "P2"], [(2026, 9, 14, 9, 0, 0.0, ["G01"])])

    with pytest.raises(RinexMergeError):
        merge_rinex2_observation_files([file1, file2], tmp_path / "merged.26o")


def test_rejects_empty_file_list(tmp_path):
    with pytest.raises(RinexMergeError):
        merge_rinex2_observation_files([], tmp_path / "merged.26o")


def test_no_filter_keeps_all_systems_untouched(tmp_path):
    satellites = ["G01", "R03", "E05", "C12"]
    file1 = build_rinex_file(tmp_path, "h1.26o", TYPES_2, [(2026, 9, 14, 8, 0, 0.0, satellites)])

    output = merge_rinex2_observation_files([file1], tmp_path / "merged.26o", keep_systems=None)

    summaries = read_epoch_summaries(output)
    assert summaries == [(4, satellites)]
