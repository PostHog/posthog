from unittest.mock import patch

from posthoganalytics.ai.prompts import PromptResult

from products.signals.backend.system_one_prompts import (
    DEFAULT_SYSTEM_ONE_MODEL,
    _parse_prompt,
    bundled_prompt,
    fetch_prompt,
)


def test_managed_prompt_keeps_policy_model_question_and_threshold_together() -> None:
    fallback = bundled_prompt("signals-actionability-issue", "old {description}", "old question", 0.85)
    policy = (
        "When in doubt, classify as ACTIONABLE.\n"
        "<issue>{description}</issue>\n"
        "Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"
    )
    result = PromptResult(
        source="api",
        name=fallback.name,
        version=2,
        prompt=policy,
        config={"model": DEFAULT_SYSTEM_ONE_MODEL, "question": "new question", "threshold": 0.91},
    )

    with (
        patch("products.signals.backend.system_one_prompts.posthoganalytics.personal_api_key", "test-key"),
        patch("products.signals.backend.system_one_prompts.Prompts") as prompts,
    ):
        prompts.return_value.get.return_value = result
        managed = fetch_prompt(fallback)

    assert managed is not None
    assert (managed.policy, managed.model, managed.question, managed.threshold, managed.version, managed.source) == (
        policy,
        DEFAULT_SYSTEM_ONE_MODEL,
        "new question",
        0.91,
        2,
        "managed",
    )
    prompts.return_value.get.assert_called_once_with(
        fallback.name,
        with_metadata=True,
        label="production",
        version=None,
        fallback=fallback.policy,
    )


def test_malformed_managed_actionability_policy_is_rejected() -> None:
    fallback = bundled_prompt("signals-actionability-issue", "old {description}", "old question", 0.85)
    result = PromptResult(
        source="api",
        name=fallback.name,
        version=3,
        prompt="Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE",
        config={"model": DEFAULT_SYSTEM_ONE_MODEL, "question": "new question", "threshold": 0.85},
    )

    assert _parse_prompt(result, fallback) is None
