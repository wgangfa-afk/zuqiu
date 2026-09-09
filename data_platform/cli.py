from __future__ import annotations

import argparse
from pathlib import Path

from .config import Settings
from .database import Database
from .recovery import create_backup, restore_backup, startup_integrity_check


def main() -> None:
    parser = argparse.ArgumentParser(description="Football Quant AI V6.0 data platform")
    parser.add_argument("command", choices=("health", "init-db", "backup", "restore"))
    parser.add_argument("--destination", type=Path, help="backup directory or new restore database path")
    parser.add_argument("--manifest", type=Path, help="manifest file used by restore")
    args = parser.parse_args()
    settings = Settings.from_environment()
    database = Database(settings.sqlite_path())
    if args.command == "restore":
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
