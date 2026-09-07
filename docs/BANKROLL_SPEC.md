# Bankroll Engine V1.0

## Monthly budget
- Monthly bankroll: ¥10,000
- Unit system: 100U
- 1U = ¥100
- The monthly bankroll is a risk budget, not a daily reset.

## Rating caps
Base exposure guidance before Kelly/risk adjustments:
- S: 1.5–2.0U
- A+: 1.0–1.5U
- A: 0.7–1.0U
- A-: 0.4–0.7U
- B+: 0–0.4U only when price threshold is satisfied
- B/C/PASS: 0U

## Fractional Kelly
Use fractional Kelly, default target 1/4 Kelly, then cap by rating and portfolio risk.

For decimal odds `o` and model win probability `p`:
- b = o - 1
- q = 1 - p
- full Kelly = (b*p - q) / b
- proposed fraction = max(0, full Kelly * 0.25)

For Asian split lines, push/half-win/half-loss markets, compute expected value from settlement states rather than binary-win Kelly.

## Risk controls
- Never increase stake to recover losses.
- Single-match exposure default cap: 2U.
- Highly correlated selections from one match share one match-exposure budget.
- Apply correlation penalty to same-team handicap, team-total, match-over and related corner/card positions.
- Daily exposure cap should be configurable and validated in backtests before production.
- Drawdown reduces Kelly multiplier automatically.
- Bankroll increases do not justify looser rating thresholds.

## Required execution fields
Every formal wager requires an immutable pre-kickoff Execution ID and:
- fixture_id
- market
- line
- odds
- bookmaker/source
- timestamp
- rating
- model probability
- fair odds
- EV
- stake U
- stake CNY
- rationale
- cancellation conditions

Post-match fields may be appended, but pre-match fields must not be rewritten.

## Accounting rule
Only Execution Book items affect official bankroll, ROI and drawdown. Analysis, WATCH, PASS and counterfactual hits never enter official P&L.
