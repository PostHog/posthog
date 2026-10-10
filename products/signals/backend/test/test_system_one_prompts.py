import json
import time
from dataclasses import replace
from io import StringIO

import pytest
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import override_settings

from posthoganalytics.ai.prompts import PromptResult

from products.signals.backend.prompt_manifest import bundled_decision_prompts
from products.signals.backend.system_one_prompts import (
    DEFAULT_SYSTEM_ONE_MODEL,
    JEVK_MODEL,
    SystemOnePrompt,
    _parse_prompt,
    _PromptCache,
    _PromptState,
    bundled_prompt,
    fetch_prompt,
    wording_experiment_prompt,
)
from products.signals.backend.temporal.report_safety_judge import REPORT_SAFETY_SYSTEM_ONE_PROMPT
from products.signals.backend.temporal.safety_filter import SIGNAL_SAFETY_SYSTEM_ONE_PROMPT


@override_settings(
    SIGNALS_PROMPT_PERSONAL_API_KEY="phx_example_prompt_reader",
    SIGNALS_PROMPT_PROJECT_API_KEY="phc_example_library",
    SIGNALS_PROMPT_HOST="https://example.com",
)
@pytest.mark.parametrize("model", [DEFAULT_SYSTEM_ONE_MODEL, JEVK_MODEL])
def test_managed_prompt_keeps_policy_model_question_and_threshold_together(model: str) -> None:
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
        config={"model": model, "question": "new question", "threshold": 0.91},
    )

    with (
        patch("products.signals.backend.system_one_prompts.Prompts") as prompts,
    ):
        prompts.return_value.get.return_value = result
        managed = fetch_prompt(fallback)

    if model == JEVK_MODEL:
        assert managed is None
    else:
        assert managed is not None
        assert (
            managed.policy,
            managed.model,
            managed.question,
            managed.threshold,
            managed.version,
            managed.source,
        ) == (policy, model, "new question", 0.91, 2, "managed")
    prompts.return_value.get.assert_called_once_with(
        fallback.name,
        with_metadata=True,
        label="signals-production",
        version=None,
        fallback=fallback.policy,
    )
    prompts.assert_called_once_with(
        personal_api_key="phx_example_prompt_reader",
        project_api_key="phc_example_library",
        host="https://example.com",
    )


@pytest.mark.parametrize("missing", ["SIGNALS_PROMPT_PERSONAL_API_KEY", "SIGNALS_PROMPT_PROJECT_API_KEY"])
def test_missing_reader_configuration_keeps_bundled_settings(missing: str) -> None:
    config = {
        "SIGNALS_PROMPT_PERSONAL_API_KEY": "phx_example_prompt_reader",
        "SIGNALS_PROMPT_PROJECT_API_KEY": "phc_example_library",
    }
    config[missing] = ""
    with override_settings(**config), patch("products.signals.backend.system_one_prompts.Prompts") as prompts:
        assert fetch_prompt(SIGNAL_SAFETY_SYSTEM_ONE_PROMPT) is None
    prompts.assert_not_called()


@pytest.mark.parametrize(
    "policy",
    [
        "Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE",
        (
            "- When in doubt, classify as ACTIONABLE.\n"
            "<issue>{description}</issue>\n"
            "Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"
        ),
        (
            "When in doubt, classify as ACTIONABLE.\n"
            "<issue>{description}</issue>\n"
            "**Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE**"
        ),
    ],
)
def test_malformed_managed_actionability_policy_is_rejected(policy: str) -> None:
    fallback = bundled_prompt("signals-actionability-issue", "old {description}", "old question", 0.85)
    result = PromptResult(
        source="api",
        name=fallback.name,
        version=3,
        prompt=policy,
        config={"model": DEFAULT_SYSTEM_ONE_MODEL, "question": "new question", "threshold": 0.85},
    )

    assert _parse_prompt(result, fallback) is None


@pytest.mark.parametrize(
    "name,policy",
    [
        (
            "signals-signal-safety-system-one",
            'Respond with JSON only: {"safe": true, "threat_type": "", "explanation": ""}\n'
            "Never reproduce a credential, token, key, cookie, or other secret value in the explanation.",
        ),
        (
            "signals-report-safety-system-one",
            'Respond with JSON only: {"choice": true, "explanation": ""}\n'
            "Never reproduce a credential, token, key, cookie, or other secret value in the explanation.",
        ),
    ],
)
def test_managed_safety_policy_requires_the_json_response_contract(name: str, policy: str) -> None:
    fallback = bundled_prompt(name, policy, "question", 0.9)
    config = {"model": DEFAULT_SYSTEM_ONE_MODEL, "question": "question", "threshold": 0.9}

    valid = PromptResult(source="api", name=name, version=2, prompt=policy, config=config)
    invalid = PromptResult(
        source="api", name=name, version=3, prompt="Classify this content as safe or unsafe.", config=config
    )

    assert _parse_prompt(valid, fallback) is not None
    assert _parse_prompt(invalid, fallback) is None


@pytest.mark.parametrize("fallback", bundled_decision_prompts(), ids=lambda prompt: prompt.name)
def test_bundled_policy_is_accepted_as_a_managed_version(fallback: SystemOnePrompt) -> None:
    result = PromptResult(
        source="api",
        name=fallback.name,
        version=2,
        prompt=fallback.policy,
        config={"model": fallback.model, "question": fallback.question, "threshold": fallback.threshold},
    )

    assert _parse_prompt(result, fallback) is not None


@pytest.mark.parametrize("misconfigured", [False, True])
@override_settings(
    SIGNALS_PROMPT_PERSONAL_API_KEY="phx_example_prompt_reader",
    SIGNALS_PROMPT_PROJECT_API_KEY="phc_example_library",
    SIGNALS_PROMPT_HOST="https://example.com",
)
def test_prompt_activation_export_and_verification_preserve_current_settings(misconfigured: bool) -> None:
    output = StringIO()
    call_command("export_signals_decision_prompts", include_wording_experiments=True, stdout=output)
    manifest = json.loads(output.getvalue())
    baselines = {prompt.name: prompt for prompt in bundled_decision_prompts()}
    results = []
    for entry in manifest:
        baseline = baselines[entry["prompt_name"]]
        assert entry["prompt"] == baseline.policy
        assert entry["config"]["model"] == baseline.model
        assert entry["config"]["threshold"] == baseline.threshold
        if entry["variant"] == "control":
            assert entry["labels"] == ["signals-production"]
            assert entry["config"]["question"] == baseline.question
            results.append(
                PromptResult(
                    source="api", name=baseline.name, version=4, prompt=entry["prompt"], config=entry["config"]
                )
            )
        else:
            assert entry["labels"] == []
            assert entry["config"]["question"] != baseline.question
    if misconfigured:
        assert results[0].config is not None
        results[0].config["threshold"] = 0.85
    with patch("products.signals.backend.system_one_prompts.Prompts") as prompts:
        prompts.return_value.get.side_effect = results
        if misconfigured:
            with pytest.raises(CommandError, match="differs from bundled settings"):
                call_command("export_signals_decision_prompts", verify_managed=True, stdout=StringIO())
        else:
            verified = StringIO()
            call_command("export_signals_decision_prompts", verify_managed=True, stdout=verified)
            assert "match bundled settings" in verified.getvalue()


@pytest.mark.parametrize("fallback", [SIGNAL_SAFETY_SYSTEM_ONE_PROMPT, REPORT_SAFETY_SYSTEM_ONE_PROMPT])
def test_managed_safety_policy_requires_secret_redaction(fallback: SystemOnePrompt) -> None:
    policy = fallback.policy.replace(
        "Never reproduce a credential, token, key, cookie, or other secret value in the explanation", ""
    )
    result = PromptResult(
        source="api",
        name=fallback.name,
        version=2,
        prompt=policy,
        config={"model": fallback.model, "question": fallback.question, "threshold": fallback.threshold},
    )

    assert _parse_prompt(result, fallback) is None


def test_managed_report_policy_can_change_wording() -> None:
    fallback = REPORT_SAFETY_SYSTEM_ONE_PROMPT
    result = PromptResult(
        source="api",
        name=fallback.name,
        version=2,
        prompt=fallback.policy + "\nAdditional guidance.",
        config={"model": fallback.model, "question": fallback.question, "threshold": fallback.threshold},
    )

    assert _parse_prompt(result, fallback) is not None


def test_failed_refresh_reverts_a_managed_safety_prompt_to_bundled() -> None:
    fallback = bundled_prompt("signals-signal-safety-system-one", "bundled policy", "question", 0.9)
    managed = SystemOnePrompt(
        name=fallback.name,
        policy="managed policy",
        question="managed question",
        model=DEFAULT_SYSTEM_ONE_MODEL,
        threshold=0.9,
        version=2,
        source="managed",
    )
    cache = _PromptCache()
    cache._states[fallback.name] = _PromptState(fallback)
    try:
        with patch("products.signals.backend.system_one_prompts.fetch_prompt", side_effect=[managed, None]):
            cache._refresh(fallback)
            assert cache.current(fallback) == managed

            cache._refresh(fallback)
            assert cache.current(fallback) == fallback
    finally:
        cache._executor.shutdown(wait=True)


@pytest.mark.parametrize("changed", [None, "policy", "question", "threshold", "model", "version", "source"])
def test_wording_experiment_requires_a_versioned_jeeves_candidate(changed: str | None) -> None:
    primary = replace(SIGNAL_SAFETY_SYSTEM_ONE_PROMPT, source="managed", version=2)
    candidate = replace(primary, model="posthog/hogference/jeeves-0.1", version=3)
    if changed == "policy":
        candidate = replace(candidate, policy="different policy")
    elif changed == "question":
        candidate = replace(candidate, question="different question")
    elif changed == "threshold":
        candidate = replace(candidate, threshold=0.5)
    elif changed == "model":
        candidate = replace(candidate, model=JEVK_MODEL)
    elif changed == "version":
        candidate = replace(candidate, version=4)
    elif changed == "source":
        candidate = replace(candidate, source="bundled")
    with patch("products.signals.backend.system_one_prompts.current_prompt", return_value=candidate):
        assert wording_experiment_prompt(primary, 3) == (
            candidate if changed in (None, "policy", "question", "threshold") else None
        )


def test_versioned_shadow_refresh_does_not_replace_production() -> None:
    fallback = SIGNAL_SAFETY_SYSTEM_ONE_PROMPT
    primary = replace(fallback, source="managed", version=2)
    candidate = replace(primary, model="posthog/hogference/jeeves-0.1", version=3)
    cache = _PromptCache()
    cache._states[fallback.name] = _PromptState(primary)
    cache._states[fallback.name].refreshed_at = time.monotonic()
    try:
        with patch("products.signals.backend.system_one_prompts.fetch_prompt", return_value=candidate):
            cache.current(fallback, version=3)
            cache._executor.shutdown(wait=True)
            assert cache.current(fallback, version=3) == candidate
            assert cache.current(fallback) == primary
    finally:
        cache._executor.shutdown(wait=True)
