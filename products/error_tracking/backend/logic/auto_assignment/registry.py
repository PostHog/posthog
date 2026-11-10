from products.error_tracking.backend.logic.auto_assignment.base import Processor
from products.error_tracking.backend.logic.auto_assignment.history import HistoryVote

# Processors run in this order and the first candidate over its threshold wins.
PROCESSORS: list[Processor] = [
    HistoryVote(),
]
