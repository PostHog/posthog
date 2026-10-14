from typing import Literal

Decision = Literal["merge", "no_merge"]
LiveDecision = Literal["merge", "no_merge", "error"]
JudgeOutcome = Literal["judged", "unavailable", "rejected", "invalid", "timeout", "no_text", "no_consent"]
JudgeBand = Literal["low", "mid", "high"]
