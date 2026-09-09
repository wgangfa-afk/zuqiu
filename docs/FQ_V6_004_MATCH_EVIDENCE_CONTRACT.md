# FQ-V6-004 Match Evidence Contract

B stores append-only, provider-attributed facts: fixture context, team metrics, player availability, and lineup observations. It does not interpret football meaning.

A alone selects time windows, weights evidence, resolves conflicting providers, and determines any probability impact. `observed_before` is the explicit historical-backtest boundary: callers must use it to prevent future-information leakage.

Evidence is source-addressed, UTC-normalized, type-checked, idempotent only by an explicit deterministic key, and retained when multiple providers disagree. B never silently merges or deletes competing records.

There is no live provider collection in this phase. This contract produces no probability, price, recommendation, BET, or Execution. The evidence tables are included in backup row counts and canonical digests; restore verifies both before publication.
