import gzip

import pytest

from app.rgp import rinex
from app.rgp.rinex import (
    RinexProcessingError,
    _is_hatanaka_filename,
    _rinex_observation_name,
    decompress,
    decompress_gzip,
    decompress_unix_z,
    process_downloaded_file,
)


def test_decompress_gzip_roundtrip(tmp_path):
    original = b"RINEX VERSION / TYPE\nligne de test\n"
    source = tmp_path / "aaer2570.26n.gz"
    source.write_bytes(gzip.compress(original))

    destination = tmp_path / "aaer2570.26n"
    result = decompress_gzip(source, destination)

    assert result == destination
    assert destination.read_bytes() == original


def test_decompress_gzip_raises_on_corrupt_file(tmp_path):
    source = tmp_path / "bad.gz"
    source.write_bytes(b"pas vraiment du gzip")
    with pytest.raises(RinexProcessingError):
        decompress_gzip(source, tmp_path / "out")


def test_decompress_unix_z_raises_on_corrupt_file(tmp_path):
    source = tmp_path / "bad.Z"
    source.write_bytes(b"pas vraiment du LZW compress")
    with pytest.raises(RinexProcessingError):
        decompress_unix_z(source, tmp_path / "out")


def test_decompress_dispatches_on_extension(tmp_path):
    original = b"contenu"
    gz_source = tmp_path / "a.gz"
    gz_source.write_bytes(gzip.compress(original))
    assert decompress(gz_source, tmp_path / "a").read_bytes() == original


def test_decompress_rejects_unknown_extension(tmp_path):
    source = tmp_path / "fichier.rnx"
    source.write_bytes(b"deja decompresse")
    with pytest.raises(RinexProcessingError):
        decompress(source, tmp_path / "out")


def test_rinex_observation_name_rinex2():
    assert _rinex_observation_name("aaer257a.26d") == "aaer257a.26o"


def test_rinex_observation_name_rinex3():
    assert _rinex_observation_name("AAER00FRA_R_20262550000_01H_30S_MO.crx") == (
        "AAER00FRA_R_20262550000_01H_30S_MO.rnx"
    )


def test_is_hatanaka_filename_detects_rinex2_observation():
    # Régression : Path("aaer257a.26d").suffix vaut ".26d", pas ".d" — un simple
    # test sur .suffix ne détecte jamais ce cas réel.
    assert _is_hatanaka_filename("aaer257a.26d")


def test_is_hatanaka_filename_detects_rinex3_observation():
    assert _is_hatanaka_filename("AAER00FRA_R_20262550000_01H_30S_MO.crx")


def test_is_hatanaka_filename_rejects_navigation_files():
    assert not _is_hatanaka_filename("aaer257a.26n")
    assert not _is_hatanaka_filename("aaer257a.26g")


def test_process_downloaded_file_converts_rinex2_observation(tmp_path, monkeypatch):
    monkeypatch.setattr(rinex.hatanaka, "decompress", lambda path: b"RINEX OBS CONTENT")

    source = tmp_path / "aaer257g.26d.Z"
    source.write_bytes(b"")  # contenu réel importe peu : decompress_unix_z est mocké ci-dessous
    monkeypatch.setattr(rinex, "decompress_unix_z", lambda src, dst: dst.write_bytes(b"CRINEX CONTENT") or dst)

    output_dir = tmp_path / "out"
    result = process_downloaded_file(source, output_dir)

    assert result.name == "aaer257g.26o"
    assert result.read_bytes() == b"RINEX OBS CONTENT"
    assert not (output_dir / "aaer257g.26d").exists()  # fichier intermédiaire nettoyé


def test_process_downloaded_file_leaves_navigation_file_as_is(tmp_path, monkeypatch):
    source = tmp_path / "aaer257g.26n.Z"
    source.write_bytes(b"")
    monkeypatch.setattr(rinex, "decompress_unix_z", lambda src, dst: dst.write_bytes(b"NAV CONTENT") or dst)

    output_dir = tmp_path / "out"
    result = process_downloaded_file(source, output_dir)

    assert result.name == "aaer257g.26n"
    assert result.read_bytes() == b"NAV CONTENT"
