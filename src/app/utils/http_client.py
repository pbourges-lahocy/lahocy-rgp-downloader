"""Client HTTP robuste (timeout + retry) pour interroger le serveur RGP IGN.

Isolé du reste de l'app pour que la politique de fiabilité réseau
(section 11 du cahier des charges) soit définie à un seul endroit.
"""

from __future__ import annotations

import logging
import ssl
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import truststore

logger = logging.getLogger(__name__)


class IgnServerUnavailableError(RuntimeError):
    """Le serveur IGN est injoignable après toutes les tentatives."""


@dataclass(frozen=True)
class HeadResult:
    exists: bool
    size_bytes: int | None
    status_code: int | None
    url: str


class RgpHttpClient:
    """Enveloppe httpx avec retries et timeouts configurables."""

    def __init__(
        self,
        timeout_seconds: float = 10.0,
        retries: int = 3,
        retry_backoff_seconds: float = 1.5,
        user_agent: str = "Lahocy-RGP-Downloader/0.1",
    ) -> None:
        self._retries = max(1, retries)
        self._retry_backoff_seconds = retry_backoff_seconds
        # Valide les certificats via le magasin de confiance du système d'exploitation
        # plutôt que le bundle certifi embarqué : nécessaire sur les postes Windows
        # d'entreprise où un proxy/pare-feu fait de l'inspection TLS avec une CA interne
        # (observé en environnement réel lors du développement de ce projet).
        ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
            verify=ssl_context,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RgpHttpClient":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def head(self, url: str) -> HeadResult:
        """Vérifie l'existence d'un fichier distant sans le télécharger (HTTP HEAD)."""
        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                response = self._client.head(url)
                if response.status_code == 200:
                    size = response.headers.get("Content-Length")
                    return HeadResult(
                        exists=True,
                        size_bytes=int(size) if size is not None else None,
                        status_code=response.status_code,
                        url=url,
                    )
                if response.status_code == 404:
                    return HeadResult(exists=False, size_bytes=None, status_code=404, url=url)
                # Statut inattendu (403, 500...) : on retente puis on remonte l'erreur.
                last_error = RuntimeError(f"Statut HTTP inattendu {response.status_code} pour {url}")
            except httpx.TimeoutException as exc:
                last_error = exc
            except httpx.TransportError as exc:
                last_error = exc

            logger.warning("Tentative %d/%d échouée pour %s : %s", attempt, self._retries, url, last_error)
            if attempt < self._retries:
                _sleep(self._retry_backoff_seconds * attempt)

        raise IgnServerUnavailableError(
            f"Le serveur RGP IGN est injoignable pour {url} après {self._retries} tentatives : {last_error}"
        )

    def get_text(self, url: str) -> str:
        """Télécharge le contenu texte d'une URL (pages d'index, fiches logsheet).

        Décode explicitement en UTF-8 avec repli Latin-1, sans se fier à la détection
        automatique d'httpx : le serveur IGN ne renvoie pas d'en-tête `Content-Type`
        avec charset sur ces fichiers, et certaines fiches (accents dans les noms de
        site) sont en réalité encodées en Latin-1/Windows-1252, pas en UTF-8.
        """
        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                response = self._client.get(url)
                response.raise_for_status()
                try:
                    return response.content.decode("utf-8")
                except UnicodeDecodeError:
                    return response.content.decode("latin-1")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise
                last_error = exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc

            logger.warning("Tentative %d/%d échouée pour %s : %s", attempt, self._retries, url, last_error)
            if attempt < self._retries:
                _sleep(self._retry_backoff_seconds * attempt)

        raise IgnServerUnavailableError(
            f"Le serveur RGP IGN est injoignable pour {url} après {self._retries} tentatives : {last_error}"
        )

    def download_to_file(self, url: str, destination: Path) -> int:
        """Télécharge un fichier binaire vers destination, retourne le nombre d'octets écrits."""
        dest_path = Path(destination)
        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                with self._client.stream("GET", url) as response:
                    response.raise_for_status()
                    total = 0
                    with dest_path.open("wb") as f:
                        for chunk in response.iter_bytes():
                            f.write(chunk)
                            total += len(chunk)
                    return total
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise
                last_error = exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc

            logger.warning("Tentative %d/%d échouée pour %s : %s", attempt, self._retries, url, last_error)
            if attempt < self._retries:
                _sleep(self._retry_backoff_seconds * attempt)

        raise IgnServerUnavailableError(
            f"Échec du téléchargement de {url} après {self._retries} tentatives : {last_error}"
        )


def _sleep(seconds: float) -> None:
    time.sleep(seconds)
