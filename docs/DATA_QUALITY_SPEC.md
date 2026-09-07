# Data Quality Specification

## Non-negotiable rule
Never fabricate odds, Asian lines, water/price, injuries, lineups, corner lines, card lines or line movement.

## Source hierarchy
1. Official league/team sources for schedule, status, lineups and official match data.
2. Specialist odds providers / bookmaker pages for live market prices.
3. Reputable statistical providers for xG, shots, corners and cards.
4. News sources for injuries/context when official confirmation is unavailable.

## Odds snapshot schema
Every market snapshot should include:
- fixture_id
- bookmaker
- market_type
- selection
- line
- price
- price_format
- source_url/source_id
- captured_at UTC
- captured_at local
- market_status
- is_opening / is_closing when known

Never overwrite history. Append new snapshots.

## Quality grades
- A: multiple bookmakers + Asian line + price/water + opening/current movement
- B: Asian line with partial movement or fewer sources
- C: 1X2/single-source/weak or incomplete market data

Additional numeric score: 0–100.

## Consensus and disagreement
Calculate:
- bookmaker consensus line
- dispersion in price
- line disagreement count
- stale-source warning
- market timestamp age

Material bookmaker disagreement should lower Market Confidence.

## Line movement
Track at minimum when available:
- opening
- T-6h
- T-3h
- T-60m
- T-15m
- close

Do not interpret line movement as money flow unless a source explicitly supplies betting percentages or exchange flow. Otherwise label as inference.

## Timezone discipline
Store kickoff in UTC and original-source timezone; render to Asia/Shanghai for user reports. Never mix local bookmaker times without conversion.

## Settlement metadata
Store bookmaker-specific rules for:
- Asian quarter lines
- three-way corner totals
- corner handicaps
- booking points
- red-card treatment
- extra time inclusion/exclusion

## Security
- Secrets live in environment variables only.
- Never commit API keys, account passwords or cookies.
- `.env` must be gitignored; only `.env.example` belongs in the repository.
