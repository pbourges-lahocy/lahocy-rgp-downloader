import datetime as dt

from app.rgp.downloader import download_station_files, has_enough_disk_space
from app.rgp.provider_ign import NAV_GPS, OBSERVATION, IgnProviderIGN


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
