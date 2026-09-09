# FQ-V6-003 Phase 1

Phase 1 accepts caller-supplied probabilities through `ModelProbability` and reads only through `ReadRepository`. It supports complete mutually exclusive normal two- or three-way markets without push or split settlement.

For a group, implied probability is `1 / decimal_odds`; de-vig probability is implied probability divided by overround. Fair odds is `1 / model_probability`, raw EV is `model_probability * market_odds - 1`, and risk-adjusted EV subtracts uncertainty, data-quality and correlation penalties.

Ratings are capped at B+. B+ requires risk-adjusted EV at least .04 and VALID data; B requires .02; C requires positive EV; otherwise PASS. B+/B map to WATCH, C/PASS map to PASS. BET is disabled because full team, lineup, tactical and market-validation models are absent.

Asian, push, half-win/loss, corner, card and player settlement models return `UNSUPPORTED_SETTLEMENT_MODEL`; they are never evaluated with the binary EV formula. Router ranks adjusted EV, raw EV, newer observation time, then snapshot ID. No A operation writes B data, Execution, settlement or bankroll.
