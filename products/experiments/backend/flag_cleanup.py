"""Decide how to tidy up an experiment's feature-flag code, and build the agent's cleanup prompt.

Pure logic shared by the manual command and (later) the automatic experiment-end trigger:
from an experiment's outcome and its flag variants, pick which variant's code path to keep,
then render the instructions handed to the coding agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.experiments.backend.models.experiment import Experiment


CONCLUSION_LABELS = {
    "won": "won",
    "lost": "lost",
    "inconclusive": "inconclusive",
    "stopped_early": "stopped early",
    "invalid": "invalid",
}

# PostHog SDK calls that read a flag, across languages — what the agent greps for.
FLAG_SDK_CALLS = (
    "isFeatureEnabled, getFeatureFlag, getFeatureFlagPayload, useFeatureFlag, useActiveFeatureFlags, "
    "onFeatureFlags, posthog.isFeatureEnabled, posthog.getFeatureFlag, feature_enabled, get_feature_flag"
)


@dataclass(frozen=True)
class CleanupPlan:
    keep_variant: str | None
    remove_variants: list[str]
    rationale: str
    confident: bool


def variant_keys(variants: list[dict]) -> list[str]:
    return [v["key"] for v in variants if v.get("key")]


def _fully_rolled_out_variant(variants: list[dict]) -> str | None:
    """After "ship a variant", the winner sits at 100% — return it if exactly one does."""
    at_100 = [v["key"] for v in variants if v.get("rollout_percentage") == 100 and v.get("key")]
    return at_100[0] if len(at_100) == 1 else None


def cleanup_plan(conclusion: str, variants: list[dict]) -> CleanupPlan:
    """Decide which variant's code path to keep, from the outcome and the flag's variants.

    "won" keeps the shipped variant (the one rolled out to 100%); a plain win with nothing
    shipped falls back to the single non-control variant as a best guess. Every other
    outcome rolls back to the baseline ("control"). Anything uncertain is marked so the
    operator (and the PR) flag it for human review rather than guessing silently.
    """
    keys = variant_keys(variants)
    non_control = [k for k in keys if k != "control"]
    has_control = "control" in keys

    def plan(keep: str | None, rationale: str, confident: bool) -> CleanupPlan:
        return CleanupPlan(
            keep_variant=keep,
            remove_variants=[k for k in keys if k != keep],
            rationale=rationale,
            confident=confident,
        )

    if conclusion == "won":
        shipped = _fully_rolled_out_variant(variants)
        if shipped:
            return plan(
                shipped,
                f'The experiment won and variant "{shipped}" was shipped (100% rollout). Keep it as the new default.',
                True,
            )
        if len(non_control) == 1:
            return plan(
                non_control[0],
                f'The experiment won but no variant is at 100% rollout. Best guess: keep the winning variant "{non_control[0]}". Confirm which variant you kept in the PR.',
                False,
            )
        return plan(
            None,
            "The experiment won, but the winning variant can't be determined automatically (more than one non-control variant). Decide per code site and explain your choice in the PR.",
            False,
        )

    keep = "control" if has_control else (keys[0] if keys else None)
    if conclusion in ("lost", "invalid"):
        return plan(
            keep,
            f'The experiment {CONCLUSION_LABELS.get(conclusion, conclusion)}. Roll back to the baseline: keep "{keep}" and remove the feature.',
            True,
        )
    return plan(
        keep,
        f'The experiment was {CONCLUSION_LABELS.get(conclusion, conclusion)}. Defaulting to the baseline "{keep}" — confirm this is the rollback you want.',
        False,
    )


def build_cleanup_prompt(experiment: Experiment, flag_key: str, plan: CleanupPlan) -> tuple[str, str]:
    """Return (title, description) — the task title and the agent's full instructions."""
    title = f"Clean up feature flag {flag_key} after experiment {experiment.id}"
    remove = ", ".join(f'"{k}"' for k in plan.remove_variants) or "(none)"
    keep_line = (
        f'- Keep the code path for variant "{plan.keep_variant}".'
        if plan.keep_variant
        else "- Keep the winning variant's code path (decide per site — see the note below)."
    )
    variants = ", ".join(variant_keys(experiment.feature_flag.variants or [])) or "(boolean / none)"

    description = "\n".join(
        [
            "Remove the scaffolding for a PostHog experiment feature flag that is no longer needed, and open a draft pull request.",
            "",
            f'Experiment: "{experiment.name}" (id {experiment.id})',
            f"Outcome: {CONCLUSION_LABELS.get(experiment.conclusion or '', experiment.conclusion or 'unknown')}",
            f'Feature flag key: "{flag_key}"',
            f"Flag variants: {variants}",
            "",
            "## What to change",
            f'Remove all references to the feature flag "{flag_key}" from this codebase and keep the correct code path.',
            keep_line,
            f"- Remove the code paths for variant(s): {remove}.",
            f'- Remove every check of the flag "{flag_key}" itself.',
            "",
            f"Why: {plan.rationale}",
            "",
            "## How to find the references",
            f'Search the repo for the flag key "{flag_key}" and for PostHog SDK calls that read flags, e.g.:',
            f"  {FLAG_SDK_CALLS}",
            "Cover every language used in the repo (JS/TS, Python, Go, Ruby, PHP, etc.).",
            "",
            "## Rules",
            "- For the kept variant: keep that branch's body, delete the surrounding flag check and the other branches.",
            "- Boolean-style checks: keep the enabled path's body and drop the if-check (and any else branch).",
            "- Remove the now-dead code you create: orphaned branches, unused imports, unused helpers.",
            "- Code only. Do NOT change the flag in PostHog, and do NOT touch unrelated code.",
            "- If the correct path is genuinely ambiguous at a site, leave it unchanged and list it in the PR description for a human to review.",
            "",
            "## Output",
            f'Open a draft pull request titled "{title}". In the description, summarise what you removed and anything you left for manual review.',
        ]
    )
    return title, description
