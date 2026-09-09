def calculate(model_probability: float, odds: float, penalties: tuple[float, float, float]) -> tuple[float, float, float]:
    fair_odds = 1 / model_probability
    raw_ev = model_probability * odds - 1
    return fair_odds, raw_ev, raw_ev - sum(penalties)
