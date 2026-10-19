from .jev import JevClient

_EXCERPT_QUESTION = "Which numbered code excerpt shows the code that the finding describes?"
_EXCERPT_LABELS = ["1", "2", "3", "4", "5"]
_MIN_EXCERPT_PROBABILITY = 0.5


def which_excerpt(finding: str, excerpts: list[str], jev: JevClient) -> int | None:
    numbered = [f"Code excerpt {index + 1}:\n{excerpt}" for index, excerpt in enumerate(excerpts)]
    item = "\n\n".join([f"Finding:\n{finding}", *numbered])
    [pick] = jev.choice([item], _EXCERPT_QUESTION, _EXCERPT_LABELS[: len(excerpts)])
    if pick is None or pick.probability < _MIN_EXCERPT_PROBABILITY:
        return None
    return int(pick.label) - 1
