# A — Analysis Engine

This directory will contain the implementation of Football Quant AI V6.0 analysis logic.

Authoritative business rules live in `docs/V6_ANALYSIS_SPEC.md`.

Planned modules:
- team strength / xG adapters
- goal models
- match-state simulation
- market router
- cross-market EV
- rating engine
- corner engine
- card engine
- recommendation reason codes

The analysis layer must remain usable independently of the Codex development workflow.
