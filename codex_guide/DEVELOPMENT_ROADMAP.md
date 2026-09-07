# Development Roadmap

## Phase 0 — Governance
- Lock V6.0 specs in `docs/`.
- Establish coding/test conventions.
- Create issue/task template with acceptance criteria.

## Phase 1 — Alpha foundation
- Python package layout
- settings/configuration
- SQLite database
- schema/migrations
- normalized entities: Fixture, Team, MarketSnapshot, Prediction, Execution, Review
- append-only odds history
- settlement library
- pytest coverage for Asian quarter lines, pushes, half-wins/half-losses, three-way corners

Acceptance: clean install, tests green, no real API dependency.

## Phase 2 — Data Platform V1
- The Odds API collector
- raw payload archive
- normalization layer
- bookmaker/source metadata
- schedule/timezone normalization
- data-quality scoring
- deduplication and stale-data checks

Acceptance: same fixture/market can be reconstructed from stored snapshots without overwriting history.

## Phase 3 — Market & EV Engine
- de-vig methods
- fair odds
- EV calculations including Asian split settlements
- market consensus/disagreement
- line-movement time series
- Market Refusal / Favorite Trap alerts

Acceptance: deterministic fixtures with golden test cases.

## Phase 4 — Analysis Engine V6 implementation
- team-strength adapters
- Poisson/Dixon-Coles interfaces
- Match State simulation interfaces
- Market Router
- rating engine
- risk-adjusted EV
- BET/WATCH/PASS reason codes

Acceptance: every recommendation explains inputs, fair price, market price, EV, risks and data quality.

## Phase 5 — Corner & Card Engines
- corner lambda/team-difference model
- card lambda/referee model
- Asian corner/card settlement
- three-way market support
- bookmaker settlement profiles

Acceptance: corner/card outputs are independent from goal predictions and have separate calibration metrics.

## Phase 6 — Bankroll & Portfolio
- ¥10,000 / 100U monthly ledger
- fractional Kelly
- rating caps
- match exposure limits
- correlation penalty
- drawdown controls

Acceptance: only immutable Execution IDs affect official P&L.

## Phase 7 — Review & backtest
- result ingestion
- automatic settlement
- CLV / ROI / drawdown
- Brier / Log Loss
- three-ledger review
- Successful PASS / Saved Loss / Missed EV / False PASS
- performance by league/market/rating/odds band

## Phase 8 — Leisu/Browser collector
Only after the structured platform is stable:
- Playwright-based local collector
- no credentials in repository
- robust selectors and legal/technical guardrails
- raw screenshot/page metadata retained when useful

## Phase 9 — ML meta-model
Only after sufficient clean history:
- LightGBM/XGBoost meta-model
- time-based train/validation splits
- leakage protection
- calibration
- compare against market-closing baseline

## Change-management rule
Every significant development should be linked to a task with explicit acceptance tests. Codex should not silently change V6 football logic; proposed logic changes belong in review first.
