def calculate(model_probability: float, odds: float, penalties: tuple[float, float, float]) -> tuple[float, float, float]:
    fair_odds = 1 / model_probability
    raw_ev = model_probability * odds - 1
    adjusted = raw_ev - sum(penalties)
    if abs(adjusted) <= 1e-12:
        adjusted = 0.0
    return fair_odds, raw_ev, adjusted
