from typing import Any, Literal

from products.replay_vision.backend.tags import slugify_tag

Outcome = Literal["kept", "regressed", "fixed", "still_wrong"]

# A summary can run long, so before/after previews cap it rather than showing the whole body.
_SUMMARY_PREVIEW_CAP = 200


def primary_outcome(model_output: dict[str, Any] | None) -> str | None:
    """The display string for before/after comparison: a discrete verdict/tags for monitors and classifiers,
    or the raw score/summary for the other types."""
    output = model_output or {}
    verdict = output.get("verdict")
    if isinstance(verdict, str) and verdict:
        return f"Verdict: {verdict.strip().lower()}"
    # Freeform tags are part of a classifier's output, so a change that only touches them must not read as
    # "no change". Matches `describe_output`, which merges both lists.
    raw_tags = [*(output.get("tags") or []), *(output.get("tags_freeform") or [])]
    tags = sorted({slug for t in raw_tags if isinstance(t, str) and (slug := slugify_tag(t))})
    if tags:
        return f"Tags: {', '.join(tags)}"
    score = output.get("score")
    if isinstance(score, int | float) and not isinstance(score, bool):
        return f"Score: {score}"
    title = output.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    summary = output.get("summary")
    if isinstance(summary, str) and summary.strip():
        trimmed = summary.strip()
        return trimmed if len(trimmed) <= _SUMMARY_PREVIEW_CAP else trimmed[:_SUMMARY_PREVIEW_CAP].rstrip() + "…"
    return None


def classify_outcome(rated_correct: bool, before: str | None, after: str | None) -> Outcome:
    """A `None` outcome is valid (e.g. a classifier with no tags)."""
    changed = before != after
    if rated_correct:
        return "regressed" if changed else "kept"
    return "fixed" if changed else "still_wrong"
