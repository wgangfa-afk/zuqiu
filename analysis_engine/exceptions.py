class AnalysisInputError(ValueError): pass
class InvalidProbabilityError(AnalysisInputError): pass
class InvalidOddsError(AnalysisInputError): pass
class MarketGroupError(AnalysisInputError): pass
class UnsupportedSettlementModelError(AnalysisInputError): pass
