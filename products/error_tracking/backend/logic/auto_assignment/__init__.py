from .base import Processor
from .history import HistoryVote

# Processors run in this order and the first candidate over its threshold wins.
PROCESSORS: list[Processor] = [
    HistoryVote(),
]
