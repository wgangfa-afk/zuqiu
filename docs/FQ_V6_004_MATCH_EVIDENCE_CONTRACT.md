# FQ-V6-004 Match Evidence Contract

B stores append-only, provider-attributed facts: fixture context, team metrics, player availability, and lineup observations. It does not interpret football meaning.

A alone selects time windows, weights evidence, resolves conflicting providers, and determines any probability impact. `observed_before` is the explicit historical-backtest boundary: callers must use it to prevent future-information leakage.

Evidence is source-addressed, UTC-normalized, type-checked, idempotent only by an explicit deterministic key, and retained when multiple providers disagree. B never silently merges or deletes competing records.

The default idempotency key is a SHA-256 hash of canonical JSON. Every identity includes the evidence type, `fixture_id`, `provider`, `raw_payload_hash`, `mapping_version`, and normalized `observed_at_utc`. Team metrics additionally include side and metric name; availability includes side plus a player identity; lineups include side, player identity, and lineup status. Player identity prefers a non-empty `player_reference`; only when absent does it use `player_name`. Fixture context includes its evidence-type marker. Thus two fixtures can never share an evidence record, and different observation times remain distinct time-series facts. All declared optional fields are normalized to `None` before insertion and comparison. An exact retry has the same key and every normalized persisted business field equal. Reusing a key with any different field is an `IdempotencyConflictError`: it fails closed, inserts nothing, and does not overwrite history.

There is no live provider collection in this phase. This contract produces no probability, price, recommendation, BET, or Execution. The evidence tables are included in backup row counts and canonical digests; restore verifies both before publication.
