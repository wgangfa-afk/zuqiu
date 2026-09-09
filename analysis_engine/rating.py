from data_platform.domain import DecisionAction


def rate(adjusted: float, valid: bool) -> tuple[str, DecisionAction]:
    """Apply Phase 1's fail-closed data-quality rating cap."""
    if not valid:
        return "PASS", DecisionAction.PASS
    if adjusted >= .04:
        return "B+", DecisionAction.WATCH
    if adjusted >= .02:
        return "B", DecisionAction.WATCH
    if adjusted > 0:
        return "C", DecisionAction.PASS
    return "PASS", DecisionAction.PASS
