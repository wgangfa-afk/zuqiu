# Codex Master Prompt — Football Quant AI V6.0

You are developing Football Quant AI V6.0 in this repository.

## Mission
Build a reliable, testable football quant platform. Do not redefine the football business logic on your own. The authoritative specifications are in `docs/`.

## Read first
1. `README.md`
2. `docs/V6_ANALYSIS_SPEC.md`
3. `docs/DATA_QUALITY_SPEC.md`
4. `docs/BANKROLL_SPEC.md`
5. `docs/REVIEW_SPEC.md`

## Architecture boundaries
- `analysis_engine/`: implementation of the analysis/routing/rating logic defined by A — Analysis Engine.
- `data_platform/`: collectors, normalized market data, historical snapshots, database, backtests and automation.
- `codex_guide/`: development tasks, acceptance criteria and architecture governance.

## Development rules
- Python 3.11+
- Modular, typed code where practical
- Tests for every settlement/calculation module
- No hard-coded credentials
- No fabricated API responses in production code
- Preserve raw source payloads before normalization where allowed
- Append odds history; never overwrite historical snapshots
- Store timestamps timezone-aware
- Distinguish Asian markets from three-way markets and bookmaker-specific card rules
- Keep Execution, Analysis and Counterfactual ledgers separate
- Do not implement default parlays

## Initial deliverable
Implement an Alpha skeleton only after the specs are committed:
1. package structure
2. configuration layer
3. SQLite schema/migrations
4. normalized domain models
5. odds snapshot repository
6. Asian-line settlement tests
7. three-way-corner settlement tests
8. execution-ledger immutability rules
9. CLI health check

Do not connect real APIs until the Alpha skeleton and tests pass.

## Acceptance mindset
Code that runs but violates football settlement logic is a failed task. In particular:
- quarter Asian lines must settle half-win/half-loss correctly
- DNB/push behavior must be correct
- three-way Over 8 is not Asian Over 8
- odds history must be append-only
- no post-match rewriting of pre-match execution fields

When uncertain about football-market semantics, stop and create a question/task rather than guessing.
