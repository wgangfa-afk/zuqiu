# FQ-V6-005 Real Odds Ingestion

The only Phase 1 provider is The Odds API V4. Calls use `/v4/sports/{sport}/events` or `/odds`; odds requests explicitly set `regions`, `markets=h2h`, `oddsFormat=decimal`, and `dateFormat=iso`. `THE_ODDS_API_KEY` is environment-only and must never be persisted, logged, or placed in a source reference.

`plan` performs neither network access nor writes. `dry-run` may consume provider quota but writes no fixture or snapshot. Only `commit` writes, in one SQLite transaction, the completed ingestion run, deduplicated raw payload, fixtures, and valid three-outcome soccer h2h bookmaker groups.

Soccer h2h maps home team to `home`, away team to `away`, and `Draw` to `draw`, with `market_type=1x2` and `settlement_type=normal`. Any incomplete, duplicate, or unknown group is rejected as a whole. B stores facts only: no probability, EV, rating, recommendation, BET, or Execution is produced.

Quota headers are retained as factual run metadata. Authentication errors are not retried; callers must apply bounded retries to rate-limit and transient transport failures. The provider request fingerprint and snapshot identity are canonical JSON SHA-256 values. Backup includes runs, payloads, and snapshot keys.
