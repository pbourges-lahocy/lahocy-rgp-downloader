import datetime as dt

import app.rgp.downloader as downloader_module
from app.rgp.downloader import (
    download_and_merge_station_files,
    download_station_files,
    has_enough_disk_space,
)
from app.rgp.provider_ign import NAV_GPS, OBSERVATION, IgnProviderIGN
from tests.rinex_fixtures import build_rinex_text


def make_candidate(file_type=OBSERVATION):
    provider = IgnProviderIGN(base_url="https://rgpdata.ign.fr/pub", data_dir="data", logsheet_dir="logsheet")
    return provider.rinex2_candidate("aaer", dt.date(2026, 9, 14), "a", 30, file_type)


class FakeDownloadClient:
    """Simule RgpHttpClient.download_to_file en écrivant un contenu gzip factice."""

    def __init__(self, content: bytes, should_fail: bool = False) -> None:
        self._content = content
        self._should_fail = should_fail

    def download_to_file(self, url, destination):
        if self._should_fail:
            raise RuntimeError("panne réseau simulée")
        destination.write_bytes(self._content)
        return len(self._content)


def test_download_station_files_without_processing(tmp_path):
    candidate = make_candidate(NAV_GPS)  # .Z, mais on ne demande pas de traitement ici
    client = FakeDownloadClient(b"contenu brut")

    results = download_station_files(client, [candidate], tmp_path / "AAER", process=False)

    assert len(results) == 1
    assert results[0].ok
    assert results[0].raw_path.read_bytes() == b"contenu brut"
    assert results[0].processed_path is None


def test_download_station_files_reports_processing_failure_but_keeps_raw_file(tmp_path):
    # Le fichier est bien téléchargé mais son contenu n'est pas un .Z valide :
    # le module doit signaler l'échec de traitement sans perdre le fichier brut.
    candidate = make_candidate(NAV_GPS)
    client = FakeDownloadClient(b"pas un vrai .Z compresse")

    results = download_station_files(client, [candidate], tmp_path / "AAER", process=True)

    assert len(results) == 1
    assert results[0].raw_path is not None
    assert not results[0].ok
    assert "non exploitable" in results[0].error


def test_download_station_files_reports_network_error(tmp_path):
    candidate = make_candidate()
    client = FakeDownloadClient(b"", should_fail=True)

    results = download_station_files(client, [candidate], tmp_path / "AAER")

    assert len(results) == 1
    assert not results[0].ok
    assert results[0].raw_path is None


def test_has_enough_disk_space_for_tiny_requirement(tmp_path):
    assert has_enough_disk_space(tmp_path, required_bytes=1024)


def test_has_enough_disk_space_rejects_absurd_requirement(tmp_path):
    absurd = 10**18  # 1 exaoctet
    assert not has_enough_disk_space(tmp_path, required_bytes=absurd)


def test_has_enough_disk_space_with_nonexistent_destination(tmp_path):
    destination = tmp_path / "does" / "not" / "exist" / "yet"
    assert has_enough_disk_space(destination, required_bytes=1024)


def _patch_process_with_fixtures(monkeypatch, fixtures: dict[str, str]) -> None:
    """Remplace process_downloaded_file par un faux qui écrit un contenu RINEX2 connu.

    Isole les tests de download_and_merge_station_files de la décompression/Hatanaka
    réelles (déjà testées ailleurs) pour ne vérifier que l'orchestration téléchargement
    -> fusion -> nettoyage.
    """

    def fake_process(raw_path, output_dir):
        obs_name = raw_path.name.rsplit(".", 2)[0] + ".26o"
        obs_path = output_dir / obs_name
        obs_path.write_text(fixtures[raw_path.name], encoding="ascii")
        return obs_path

    monkeypatch.setattr(downloader_module, "process_downloaded_file", fake_process)


def test_download_and_merge_combines_two_hourly_files(tmp_path, monkeypatch):
    provider = IgnProviderIGN(base_url="https://rgpdata.ign.fr/pub", data_dir="data", logsheet_dir="logsheet")
    c1 = provider.rinex2_candidate("aaer", dt.date(2026, 9, 14), "g", 30, OBSERVATION)
    c2 = provider.rinex2_candidate("aaer", dt.date(2026, 9, 14), "h", 30, OBSERVATION)
    types = ["L1", "C1"]
    fixtures = {
        c1.filename: build_rinex_text(types, [(2026, 9, 14, 6, 0, 0.0, ["G01"])]),
        c2.filename: build_rinex_text(types, [(2026, 9, 14, 7, 0, 0.0, ["G02"])]),
    }
    _patch_process_with_fixtures(monkeypatch, fixtures)

    result = download_and_merge_station_files(
        FakeDownloadClient(b"peu importe"), [c1, c2], tmp_path / "AAER", date=dt.date(2026, 9, 14)
    )

    assert result.merge_error is None
    assert result.merged_path is not None
    assert result.merged_path.name == "aaer257_0600-0800.26o"
    assert result.merged_path.exists()
    # Les fichiers horaires individuels sont nettoyés une fois fusionnés.
    assert not (tmp_path / "AAER" / "aaer257g.26o").exists()
    assert not (tmp_path / "AAER" / "aaer257h.26o").exists()
    # Les fichiers bruts téléchargés (.Z) restent en revanche disponibles.
    assert (tmp_path / "AAER" / c1.filename).exists()


def test_download_and_merge_single_file_without_filter_skips_merge(tmp_path, monkeypatch):
    provider = IgnProviderIGN(base_url="https://rgpdata.ign.fr/pub", data_dir="data", logsheet_dir="logsheet")
    c1 = provider.rinex2_candidate("aaer", dt.date(2026, 9, 14), "g", 30, OBSERVATION)
    types = ["L1", "C1"]
    fixtures = {c1.filename: build_rinex_text(types, [(2026, 9, 14, 6, 0, 0.0, ["G01"])])}
    _patch_process_with_fixtures(monkeypatch, fixtures)

    result = download_and_merge_station_files(
        FakeDownloadClient(b"peu importe"), [c1], tmp_path / "AAER", date=dt.date(2026, 9, 14)
    )

    assert result.merge_error is None
    assert result.merged_path.name == "aaer257g.26o"  # nom inchangé : aucune fusion nécessaire


def test_download_and_merge_single_file_with_filter_still_merges(tmp_path, monkeypatch):
    provider = IgnProviderIGN(base_url="https://rgpdata.ign.fr/pub", data_dir="data", logsheet_dir="logsheet")
    c1 = provider.rinex2_candidate("aaer", dt.date(2026, 9, 14), "g", 30, OBSERVATION)
    types = ["L1", "C1"]
    fixtures = {c1.filename: build_rinex_text(types, [(2026, 9, 14, 6, 0, 0.0, ["G01", "R03"])])}
    _patch_process_with_fixtures(monkeypatch, fixtures)

    result = download_and_merge_station_files(
        FakeDownloadClient(b"peu importe"),
        [c1],
        tmp_path / "AAER",
        date=dt.date(2026, 9, 14),
        keep_systems={"G"},
    )

    assert result.merge_error is None
    assert result.merged_path.name == "aaer257_0600-0700_G.26o"
    assert "R03" not in result.merged_path.read_text(encoding="ascii")


def test_download_and_merge_reports_error_without_losing_individual_files(tmp_path, monkeypatch):
    provider = IgnProviderIGN(base_url="https://rgpdata.ign.fr/pub", data_dir="data", logsheet_dir="logsheet")
    c1 = provider.rinex2_candidate("aaer", dt.date(2026, 9, 14), "g", 30, OBSERVATION)
    c2 = provider.rinex2_candidate("aaer", dt.date(2026, 9, 14), "h", 30, OBSERVATION)
    fixtures = {
        c1.filename: build_rinex_text(["L1", "C1"], [(2026, 9, 14, 6, 0, 0.0, ["G01"])]),
        c2.filename: build_rinex_text(["L1", "C1", "P2"], [(2026, 9, 14, 7, 0, 0.0, ["G02"])]),
    }
    _patch_process_with_fixtures(monkeypatch, fixtures)

    result = download_and_merge_station_files(
        FakeDownloadClient(b"peu importe"), [c1, c2], tmp_path / "AAER", date=dt.date(2026, 9, 14)
    )

    assert result.merge_error is not None
    assert result.merged_path is None
    # Les fichiers individuels ne doivent pas être perdus si la fusion échoue.
    assert (tmp_path / "AAER" / "aaer257g.26o").exists()
    assert (tmp_path / "AAER" / "aaer257h.26o").exists()
