from __future__ import annotations

import argparse
from pathlib import Path

from .config import Settings
from .database import Database
from .recovery import create_backup, restore_backup, startup_integrity_check
from .ingestion.client import OddsApiClient, UrllibHttpClient
from .ingestion.service import OddsIngestionService


def main() -> None:
    parser = argparse.ArgumentParser(description="Football Quant AI V6.0 data platform")
    parser.add_argument("command", choices=("health", "init-db", "backup", "restore", "odds-ingest"))
    parser.add_argument("--destination", type=Path, help="backup directory or new restore database path")
    parser.add_argument("--manifest", type=Path, help="manifest file used by restore")
    parser.add_argument("--sport", help="The Odds API soccer sport key")
    parser.add_argument("--regions", help="explicit comma-separated provider regions")
    parser.add_argument("--mode", choices=("plan", "dry-run", "commit"), default="plan")
    args = parser.parse_args()
    settings = Settings.from_environment()
    database = Database(settings.sqlite_path())
    if args.command == "odds-ingest":
        if not args.sport or not (args.regions or settings.odds_regions):
            parser.error("odds-ingest requires --sport and explicit --regions (or THE_ODDS_REGIONS)")
        regions = args.regions or settings.odds_regions
        if args.mode == "plan":
            print(OddsIngestionService(database, None).plan(args.sport, regions))
            return
        database.initialize()
        report = startup_integrity_check(database)
        if not report.ok:
            raise SystemExit(f"RECOVERY_REQUIRED: {report.errors}")
        client = OddsApiClient.from_environment(UrllibHttpClient(), settings.odds_min_remaining_credits)
        result = OddsIngestionService(database, client).ingest(sport=args.sport, regions=regions, mode=args.mode)
        print({"received": result.records_received, "written": result.records_written, "rejected": result.records_rejected, "quota_remaining": result.quota.remaining})
    elif args.command == "restore":
        if args.manifest is None or args.destination is None:
            parser.error("restore requires --manifest and --destination")
        restored = restore_backup(args.manifest, args.destination)
        print(f"restored and verified SQLite database: {restored.path}")
    elif args.command == "init-db":
        database.initialize()
        print(f"initialized SQLite database: {settings.sqlite_path()}")
    elif args.command == "backup":
        if args.destination is None:
            parser.error("backup requires --destination")
        database.initialize()
        report = startup_integrity_check(database)
        if not report.ok:
            raise SystemExit(f"RECOVERY_REQUIRED: {report.errors}")
        manifest = create_backup(database, args.destination)
        print(f"created and verified backup manifest: {manifest}")
    else:
        database.initialize()
        report = startup_integrity_check(database)
        if not report.ok:
            raise SystemExit(f"RECOVERY_REQUIRED: {report.errors}")
        print(f"ok timezone={settings.timezone} database={settings.database_url}")


if __name__ == "__main__":
    main()
