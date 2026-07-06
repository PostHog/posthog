"""Step registry: maps a step name to its dataset and runner.

A single place both the management command and the pytest entrypoints use to discover
cases, so adding a step (e.g. ``grouping``) is a one-line change here plus the dataset.

Live mode = the small hand-authored live-calibrated cases **plus** the large generated suite
(``cases/generated/*.json``, produced by ``generate_eval_cases``). The generated suite is what
makes the eval broad enough to compare models/prompts; the hand-authored ones are curated
anchors. Replay mode uses only the cassette-backed regression cases.
"""

from __future__ import annotations

from products.signals.eval.agentic.datasets import EvalCase

STEPS: tuple[str, ...] = ("research", "repo_selection", "implementation")


def _curated_live(step: str) -> list[EvalCase]:
    if step == "research":
        from products.signals.eval.agentic.cases.research_live import CASES  # noqa: PLC0415

        return list(CASES)
    if step == "repo_selection":
        from products.signals.eval.agentic.cases.repo_selection_live import CASES  # noqa: PLC0415

        return list(CASES)
    from products.signals.eval.agentic.cases.implementation_live import CASES  # noqa: PLC0415

    return list(CASES)


def _replay(step: str) -> list[EvalCase]:
    if step == "research":
        from products.signals.eval.agentic.cases.research import CASES  # noqa: PLC0415

        return list(CASES)
    if step == "repo_selection":
        from products.signals.eval.agentic.cases.repo_selection import CASES  # noqa: PLC0415

        return list(CASES)
    from products.signals.eval.agentic.cases.implementation import CASES  # noqa: PLC0415

    return list(CASES)


def load_cases(step: str, *, mode: str = "replay", include_generated: bool = True) -> list[EvalCase]:
    if step not in STEPS:
        raise KeyError(f"unknown step {step!r}; known: {STEPS}")
    if mode != "live":
        return _replay(step)
    cases = _curated_live(step)
    if include_generated:
        from products.signals.eval.agentic.cases.generated import load_generated  # noqa: PLC0415

        seen = {c.case_id for c in cases}
        cases = cases + [c for c in load_generated(step) if c.case_id not in seen]
    return cases
