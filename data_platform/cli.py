from __future__ import annotations

import argparse

from .config import Settings
from .database import Database


def main() -> None:
    parser = argparse.ArgumentParser(description="Football Quant AI V6.0 data platform")
    parser.add_argument("command", choices=("health", "init-db"))
    args = parser.parse_args()
    settings = Settings.from_environment()
    database = Database(settings.sqlite_path())
    if args.command == "init-db":
        database.initialize()
        print(f"initialized SQLite database: {settings.sqlite_path()}")
    else:
        database.initialize()
        print(f"ok timezone={settings.timezone} database={settings.database_url}")


if __name__ == "__main__":
    main()
