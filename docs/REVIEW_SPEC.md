# Review Engine V1.0 — Full-Decision Counterfactual Review

## Objective
Review every analyzed decision, not only wagers.

## Three ledgers
### 1. Execution Book
Only pre-match locked wagers. Used for:
- official hit/settlement rate
- P&L
- ROI
- CLV
- drawdown
- bankroll curve

### 2. Analysis Book
All analyzed directions that were not formally executed, including B+/B/WATCH/conditional views. Used for:
- Direction Accuracy
- rating calibration
- model-vs-market diagnostics

### 3. Counterfactual Book
Markets mentioned or logically routed but not executed. Used for:
- Successful PASS
- Saved Loss
- Potential Missed EV
- False PASS
- Market Router learning

Never mix these ledgers.

## Review categories
- BET + hit: why model and price were correct
- BET + miss: randomness vs model error vs market-choice error
- PASS + direction hit: was PASS still correct because price was poor?
- PASS + direction miss: did the filter save a loss?
- Router miss: match thesis was right but a better tradable market was not captured

## Metrics
- Direction Accuracy
- Market Selection Accuracy
- PASS Efficiency
- Saved Loss Rate
- Missed EV Rate
- Cross-Market Capture
- Brier Score
- Log Loss
- CLV
- ROI
- Maximum Drawdown
- performance by league
- performance by market type
- performance by odds band
- performance by rating

## Anti-hindsight rule
A market that hit after being passed is not automatically a missed bet. Evaluate the pre-match fair probability and price. Do not infer EV from outcome alone.

## Required post-match record
- final score
- settlement state: win/half-win/push/half-loss/loss
- actual P&L
- closing odds / closing line when available
- CLV
- key match statistics
- red cards / penalties / major events
- model error type
- market-choice error type
- whether PASS reason remained valid
- recommended model-weight change, if any

## Error taxonomy
Suggested tags:
- FAVORITE_OVERWEIGHT
- MARKET_REFUSAL_IGNORED
- LINE_MOVE_IGNORED
- DRAW_RISK_UNDERWEIGHT
- ROTATION_UNCERTAINTY
- FATIGUE_UNDERWEIGHT
- CONVERSION_VARIANCE
- CORNER_MODEL_ERROR
- CARD_MODEL_ERROR
- ROUTER_MISSED_MARKET
- PRICE_TOO_LOW
- DATA_QUALITY_FAILURE
- CORRELATION_OVEREXPOSURE

## Learned review rules
- Do not change weights because of a single result unless the failure exposes a structural bug.
- Keep outcome quality and decision quality separate.
- A late winning goal may still be a weak-process win.
- A losing match may still validate a secondary script, e.g. territory/corners while the side loses.
- PASS data is training data and must be retained.
