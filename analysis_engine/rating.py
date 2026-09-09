from data_platform.domain import DecisionAction

def rate(adjusted: float, valid: bool) -> tuple[str, DecisionAction]:
    if adjusted >= .04 and valid: return "B+", DecisionAction.WATCH
    if adjusted >= .02: return "B", DecisionAction.WATCH
    if adjusted > 0: return "C", DecisionAction.PASS
    return "PASS", DecisionAction.PASS
