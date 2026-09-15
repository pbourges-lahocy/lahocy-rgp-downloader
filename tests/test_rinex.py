import gzip

import pytest

from app.rgp.rinex import (
    RinexProcessingError,
    _rinex_observation_name,
    decompress,
    decompress_gzip,
    decompress_unix_z,
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
