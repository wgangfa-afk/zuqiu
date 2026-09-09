# A Read Contract Foundation

Analysis Engine may depend only on `data_platform.read_models` DTOs and `data_platform.read_api.ReadRepository` for persisted B data. It must not call `Database.connection()` or use SQLite table names.

DTOs are frozen, slots dataclasses: `FixtureRecord`, `MarketSnapshotRecord`, `AnalysisDecisionRecord`, `ExecutionRecord`, and `SettlementRecord`. Their fields mirror the documented persistence fields; all timestamps are UTC-aware `datetime` objects. `LedgerBook`, `DecisionAction`, `ExecutionStatus`, and `SettlementOutcome` are reused enums. Market identifiers and validation fields remain strings.

`ReadRepository(database)` requires `database.health_state == "HEALTHY"`. `UNVERIFIED` and `RECOVERY_REQUIRED` raise `DatabaseNotHealthyError`; reads never mark a database healthy. Required getters raise `RecordNotFoundError`; `get_settlement()` returns `None` only for an existing, unsettled execution. List limits are 1–5000 and invalid limits or non-UTC/naive time filters raise `InvalidReadFilterError`.

Public methods are `get_fixture`, `list_market_snapshots`, `get_analysis_decision`, `list_analysis_decisions`, `get_execution`, `list_executions`, and `get_settlement`. Lists return immutable tuples and sort snapshots by `observed_at_utc, id`, decisions by `created_at_utc, id`, and executions by `created_at_utc, id`.

This contract is read-only. It contains no prediction, probability, theoretical pricing, EV, rating, router, recommendation, or staking logic.
