# V6 Analysis Specification

## 1. Objective
Football Quant AI V6.0 is a trading-oriented football analysis engine. The target is long-run positive EV, not simply picking winners.

## 2. Core workflow
1. Scan all relevant fixtures in the requested time window.
2. Verify schedule and market availability.
3. Build team-strength and match-state priors.
4. Estimate fair 1X2 / handicap / totals.
5. Compare with live market prices after de-vig.
6. Route to alternate markets when the primary market is inefficient.
7. Apply market-refusal, favorite-trap, injury, fatigue and lineup vetoes.
8. Rank by risk-adjusted EV and correlation.
9. Output BET / WATCH / PASS with explicit reasons.
10. Re-price at T-60m and T-15m when possible.

## 3. Model components
- Elo / team strength / league-strength adjustment
- xG/xGA, shots, shots on target, box entries, conversion and defensive-error rates
- Poisson / Dixon-Coles / Skellam where appropriate
- Time decay and recent form
- Home/away effects
- Injuries, suspensions, expected/confirmed XI, goalkeeper changes
- Rotation, fatigue, travel, schedule congestion, motivation
- Tactical matchup and match-control coefficient
- Draw-risk coefficient
- Underdog false-safety coefficient
- Market Refusal Score
- Favorite Trap Score
- Bad Form Reversal Score

## 4. Market Router
A low-value primary market does NOT imply a match-level PASS.

Routing order may include:
- 1X2 / moneyline
- Asian handicap / European handicap / spread
- Totals / Asian totals
- BTTS
- Team totals
- Half markets
- Corners totals
- Asian corners / corner handicap / team corners
- Three-way corner totals
- Cards totals
- Card handicap / team cards
- Player-card markets when data quality permits

Every routed market must be independently priced. Never choose a market merely because its decimal odds are higher.

## 5. Match State Simulation
Simulate likely time spent in states such as 0-0, 1-0, 0-1, 1-1, 2-0 and adjust:
- scoring intensity
- shooting rate
- corner rate
- foul/card rate
- tempo and pressing behavior

## 6. Corner Engine
Corners are an independent target variable. Inputs should include:
- team corners for/against
- crossing rate and wide-attack share
- blocked shots
- attacking-third entries
- opponent clearance style
- possession/control
- trailing-state corner uplift
- leading-state corner decay
- home/away

Outputs:
- total corners distribution
- team corners distribution
- corner difference distribution
- Asian corner totals
- corner handicap
- team-corner totals
- first-half corner markets
- three-way corner markets

Important: three-way Over 8 means 9+ wins; exactly 8 is a separate outcome. Do not settle it like Asian Over 8.

## 7. Card Engine
Inputs:
- referee cards per match
- foul-to-card conversion
- team/player card rates
- pressing/tackling profile
- transition-defense fouls
- derby/importance context
- match state

Outputs:
- total cards
- team cards
- card handicap
- player-card probabilities when reliable

Bookmaker settlement rules for red cards / booking points must be stored per provider.

## 8. Cross-Market EV
For each candidate record:
- model probability
- de-vig market probability
- fair odds
- market odds
- raw EV
- uncertainty penalty
- data-quality penalty
- correlation penalty
- risk-adjusted EV

## 9. Market anomalies
Raise warnings when:
- model says strong favorite but market refuses to deepen
- strong favorite line retreats across bookmakers
- Asian and European markets diverge materially
- bookmakers disagree on the main line
- lineup/news cannot explain the divergence

An unexplained red-flag anomaly caps the rating below A.

## 10. Rating system
- S: rare elite opportunity; all major evidence aligned
- A+: very strong positive EV
- A: clear positive EV
- A-: positive EV with one meaningful risk
- B+: conditional / watchlist
- B: directional view only
- C: insufficient or conflicting data
- PASS: no tradable edge

S should be rare. No quota for S/A picks.

## 11. Hard rules learned from review
- Strong team + ranking + winning streak must never dominate the model.
- A favorite line retreat must trigger re-pricing of AH, 1X2, team totals, O/U and BTTS. Never automatically switch from a risky handicap to an over.
- Bad-form underdogs require a reversal warning when the market refuses to strengthen the opponent.
- High-scoring expectation is not a proxy for high corners.
- High intensity is not a proxy for high cards without referee support.
- Market favorite does not equal positive EV.
- Low-price favorites should be routed to deeper handicap, team totals, corners and cards before declaring MATCH PASS.
