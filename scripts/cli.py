#!/usr/bin/env python
"""RGP Downloader Lahocy — ligne de commande (Phases 2 et 3).

À partir d'une position de chantier, d'une date et d'une plage horaire,
détermine les stations RGP les plus proches, vérifie en ligne quelles
données sont réellement disponibles, et affiche exactement les fichiers
concernés.

Sans --download : dry-run, rien n'est téléchargé (Phase 2).
Avec --download DEST : télécharge réellement les fichiers disponibles pour
les stations sélectionnées vers DEST/RGP/AAAA-MM-JJ/STATION/, les rend
exploitables (décompression + conversion Hatanaka si besoin), et écrit
DEST/RGP/AAAA-MM-JJ/rapport_RGP.txt (Phase 3).

Exemples :

    python scripts/cli.py --x 648237.66 --y 6862271.99 \\
        --date 14/09/2026 --start 08:15 --end 17:45

    python scripts/cli.py --lat 48.8566 --lon 2.3522 \\
        --date 14/09/2026 --full-day --count 5 --download D:\\Chantiers
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

# La console Windows utilise par défaut un encodage (cp1252) incapable d'afficher
# certains caractères présents dans les noms de station ou les messages d'avertissement.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app.config.loader import load_config  # noqa: E402
from app.geo.coordinates import InvalidCoordinatesError, lambert93_to_wgs84, wgs84_to_lambert93  # noqa: E402
from app.rgp.availability import AvailabilityStatus, check_availability_for_utc_period  # noqa: E402
from app.rgp.catalog import get_catalog  # noqa: E402
from app.rgp.downloader import download_and_merge_station_files, has_enough_disk_space  # noqa: E402
from app.rgp.provider_ign import IgnProviderIGN  # noqa: E402
from app.rgp.report import ChantierInfo, StationReportEntry, build_report  # noqa: E402
from app.rgp.rinex_merge import GNSS_SYSTEMS  # noqa: E402
from app.rgp.stations import find_nearest  # noqa: E402
from app.utils.dates import local_range_to_utc  # noqa: E402
from app.utils.http_client import IgnServerUnavailableError, RgpHttpClient  # noqa: E402

DEFAULT_TIMEZONE = "Europe/Paris"


class InputError(ValueError):
    """Erreur de saisie utilisateur, affichée proprement sans traceback."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    loc_group = parser.add_argument_group("Localisation du chantier (une seule méthode)")
    loc_group.add_argument("--x", type=float, help="Coordonnée X Lambert-93 (EPSG:2154)")
    loc_group.add_argument("--y", type=float, help="Coordonnée Y Lambert-93 (EPSG:2154)")
    loc_group.add_argument("--lat", type=float, help="Latitude WGS84 (degrés décimaux)")
    loc_group.add_argument("--lon", type=float, help="Longitude WGS84 (degrés décimaux)")

    parser.add_argument("--date", required=True, help="Date du chantier, format JJ/MM/AAAA")
    parser.add_argument("--start", help="Heure de début, format HH:MM (ignoré si --full-day)")
    parser.add_argument("--end", help="Heure de fin, format HH:MM (ignoré si --full-day)")
    parser.add_argument("--full-day", action="store_true", help="Journée entière")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help=f"Fuseau horaire local (défaut : {DEFAULT_TIMEZONE})")
    parser.add_argument("--count", type=int, default=None, help="Nombre de stations à considérer (défaut : config)")
    parser.add_argument("--cadence", type=int, default=None, help="Cadence souhaitée en secondes (défaut : config)")
    parser.add_argument("--refresh-catalog", action="store_true", help="Force le re-téléchargement du catalogue de stations")
    parser.add_argument("--config", type=Path, default=None, help="Chemin vers config.yaml")
    parser.add_argument(
        "--download",
        type=Path,
        default=None,
        metavar="DOSSIER",
        help="Télécharge réellement les fichiers vers DOSSIER/RGP/AAAA-MM-JJ/STATION/ "
        "(sans cette option : dry-run, rien n'est téléchargé)",
    )
    parser.add_argument(
        "--constellations",
        default=None,
        metavar="G,R,E,...",
        help="Constellations à conserver, séparées par des virgules parmi "
        f"{'/'.join(GNSS_SYSTEMS)} ({', '.join(GNSS_SYSTEMS.values())}). "
        "Par défaut : aucun filtrage, tout est conservé.",
    )

    return parser.parse_args(argv)


def parse_constellations(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    letters = {code.strip().upper() for code in raw.split(",") if code.strip()}
    unknown = letters - GNSS_SYSTEMS.keys()
    if unknown:
        raise InputError(
            f"Constellation(s) inconnue(s) : {', '.join(sorted(unknown))}. "
            f"Valeurs possibles : {'/'.join(GNSS_SYSTEMS)}."
        )
    return letters


def resolve_site_coordinates(args: argparse.Namespace) -> tuple[float, float, float, float]:
    """Retourne (lat, lon, x_l93, y_l93) à partir des arguments, quelle que soit la méthode saisie."""
    has_l93 = args.x is not None and args.y is not None
    has_wgs84 = args.lat is not None and args.lon is not None

    if has_l93 and has_wgs84:
        raise InputError("Fournissez soit X/Y Lambert-93, soit latitude/longitude — pas les deux.")
    if not has_l93 and not has_wgs84:
        raise InputError("Fournissez la position du chantier : --x/--y (Lambert-93) ou --lat/--lon (WGS84).")

    if has_l93:
        lat, lon = lambert93_to_wgs84(args.x, args.y)
        return lat, lon, args.x, args.y

    x, y = wgs84_to_lambert93(args.lat, args.lon)
    return args.lat, args.lon, x, y


def parse_site_date(raw: str) -> dt.date:
    try:
        date = dt.datetime.strptime(raw, "%d/%m/%Y").date()
    except ValueError as exc:
        raise InputError(f"Date invalide {raw!r} : format attendu JJ/MM/AAAA.") from exc

    if date > dt.date.today():
        raise InputError(
            f"La date indiquée ({raw}) est dans le futur : "
            "le RGP ne peut pas fournir de données qui n'ont pas encore été enregistrées."
        )
    return date


def parse_clock_time(raw: str, label: str) -> dt.time:
    try:
        return dt.datetime.strptime(raw, "%H:%M").time()
    except ValueError as exc:
        raise InputError(f"Heure {label} invalide {raw!r} : format attendu HH:MM.") from exc


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        lat, lon, x_l93, y_l93 = resolve_site_coordinates(args)
        site_date = parse_site_date(args.date)

        if args.full_day:
            start_time = end_time = None
        else:
            if not args.start or not args.end:
                raise InputError("Précisez --start et --end, ou utilisez --full-day.")
            start_time = parse_clock_time(args.start, "de début")
            end_time = parse_clock_time(args.end, "de fin")

        start_utc, end_utc = local_range_to_utc(site_date, start_time, end_time, args.full_day, args.timezone)
        keep_systems = parse_constellations(args.constellations)
    except (InputError, InvalidCoordinatesError, ValueError) as exc:
        print(f"Erreur de saisie : {exc}", file=sys.stderr)
        return 1

    config = load_config(args.config)
    count = args.count or config.selection.default_station_count
    cadence = args.cadence or config.selection.default_cadence
    period_label = "journée entière" if args.full_day else f"{args.start} -> {args.end}"

    print("=== Chantier ===")
    print(f"Lambert-93 : X={x_l93:.2f}  Y={y_l93:.2f}")
    print(f"WGS84      : lat={lat:.6f}  lon={lon:.6f}")
    print(f"Date       : {site_date.strftime('%d/%m/%Y')}  ({args.timezone})")
    print(f"Période    : {period_label}")
    print(f"UTC        : {start_utc.strftime('%Y-%m-%d %H:%M')} -> {end_utc.strftime('%Y-%m-%d %H:%M')}")
    print()

    provider = IgnProviderIGN(
        base_url=config.ign.base_url, data_dir=config.ign.data_dir, logsheet_dir=config.ign.logsheet_dir
    )
    report_entries: list[StationReportEntry] = []

    try:
        with RgpHttpClient(
            timeout_seconds=config.network.timeout_seconds,
            retries=config.network.retries,
            retry_backoff_seconds=config.network.retry_backoff_seconds,
            user_agent=config.network.user_agent,
        ) as client:
            print("Chargement du catalogue des stations RGP...")
            stations = get_catalog(
                client,
                provider,
                config.cache_dir,
                config.cache.catalog_filename,
                config.cache.catalog_ttl_days,
                force_refresh=args.refresh_catalog,
            )
            print(f"{len(stations)} stations connues.\n")

            nearest = find_nearest(stations, lat, lon, limit=count)

            print(f"=== {len(nearest)} station(s) RGP les plus proches ===\n")
            for rank, sd in enumerate(nearest, start=1):
                station = sd.station
                print(f"{rank}. {station.code.upper()} — {station.name} ({sd.distance_km:.1f} km)")
                if sd.distance_km > 100:
                    print("   ⚠ Station particulièrement éloignée du chantier.")
                print(f"   Constellations (config. actuelle) : {station.satellite_system}")

                availability = check_availability_for_utc_period(
                    client,
                    provider,
                    station.code,
                    start_utc,
                    end_utc,
                    full_day=args.full_day,
                    cadence=cadence,
                    other_cadences=config.ign.cadences,
                )

                _print_availability(availability)
                report_entries.append(StationReportEntry(station=station, distance_km=sd.distance_km, availability=availability))
                print()

            if args.download:
                _run_downloads(client, args.download, site_date, report_entries, keep_systems)
    except IgnServerUnavailableError as exc:
        print(f"\nErreur : le serveur RGP IGN est actuellement inaccessible.\n{exc}", file=sys.stderr)
        return 2

    if args.download:
        chantier = ChantierInfo(x_l93=x_l93, y_l93=y_l93, lat=lat, lon=lon, site_date=site_date, period_label=period_label)
        report_text = build_report(chantier, report_entries, generated_at=dt.datetime.now())
        chantier_dir = args.download / "RGP" / site_date.isoformat()
        chantier_dir.mkdir(parents=True, exist_ok=True)
        report_path = chantier_dir / "rapport_RGP.txt"
        report_path.write_text(report_text, encoding="utf-8")
        print(f"\nRapport écrit : {report_path}")

    return 0


def _run_downloads(
    client, download_root: Path, site_date: dt.date, entries: list[StationReportEntry], keep_systems: set[str] | None
) -> None:
    downloadable = [e for e in entries if e.availability.status != AvailabilityStatus.INDISPONIBLE and e.availability.files]
    if not downloadable:
        print("=== Téléchargement ===\nAucune station disponible à télécharger.\n")
        return

    total_size = sum(e.availability.total_size_bytes for e in downloadable)
    chantier_dir = download_root / "RGP" / site_date.isoformat()
    if not has_enough_disk_space(download_root, total_size):
        print(
            f"\nErreur : espace disque insuffisant sur {download_root} "
            f"(besoin estimé : {total_size / (1024 * 1024):.1f} Mo). Téléchargement annulé.",
            file=sys.stderr,
        )
        return

    print(f"=== Téléchargement vers {chantier_dir} ===\n")
    for entry in downloadable:
        station_dir = chantier_dir / entry.station.code.upper()
        print(f"{entry.station.code.upper()} -> {station_dir}")
        result = download_and_merge_station_files(client, entry.availability.files, station_dir, site_date, keep_systems)
        entry.downloaded_files = result.downloaded_files
        entry.merged_path = result.merged_path
        entry.merge_error = result.merge_error
        entry.constellations_kept = keep_systems

        for f in result.downloaded_files:
            if not f.ok:
                print(f"   ✗ {f.candidate.filename} : {f.error}")
        if result.merged_path:
            print(f"   ✓ {result.merged_path.name}")
        elif result.merge_error:
            print(f"   ✗ Fusion échouée : {result.merge_error}")
        print()


def _print_availability(result) -> None:
    status_labels = {
        AvailabilityStatus.DISPONIBLE: "Disponible",
        AvailabilityStatus.PARTIEL: "Partiel",
        AvailabilityStatus.INDISPONIBLE: "Indisponible",
    }
    print(f"   État : {status_labels[result.status]}")

    if result.files:
        print("   Fichiers qui seraient téléchargés :")
        for f in result.files:
            print(f"     - {f.url}")
        if result.total_size_bytes:
            print(f"   Taille totale estimée : {result.total_size_bytes / 1024:.0f} Ko")
    else:
        print("   Aucun fichier disponible pour cette période à cette cadence.")

    for warning in result.warnings:
        print(f"   ⚠ {warning}")


if __name__ == "__main__":
    raise SystemExit(main())
