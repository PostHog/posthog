from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from parameterized import parameterized

from posthog.models.team.team import Team

from products.signals.backend.scout_harness.model_selection import GLM_MODEL, ScoutModel, resolve_scout_model

_PAYLOAD_PATH = "products.signals.backend.scout_harness.model_selection.posthoganalytics.get_feature_flag_payload"

_TEAM_ID = 2
_SKILL = "signals-scout-team-self-driving"
_OTHER_SKILL = "signals-scout-errors"
_GPT = "gpt-5.5"
_RUN_ID = "0190a000-0000-7000-8000-000000000001"


def _fake_team(team_id: int = _TEAM_ID, parent_team_id: int | None = None) -> Team:
    # resolve_scout_model only reads id + parent_team_id, so a lightweight stand-in avoids the DB.
    return cast(Team, SimpleNamespace(id=team_id, parent_team_id=parent_team_id))


def _resolve_full(
    skill: str = _SKILL, run_id: str = _RUN_ID, *, team: Team | None = None, payload: object
) -> ScoutModel:
    with patch(_PAYLOAD_PATH, return_value=payload):
        return resolve_scout_model(team or _fake_team(), skill, run_id)


def _resolve(skill: str = _SKILL, run_id: str = _RUN_ID, *, team: Team | None = None, payload: object) -> str | None:
    return _resolve_full(skill=skill, run_id=run_id, team=team, payload=payload).model


def _scouts(scouts: dict, team_id: int = _TEAM_ID) -> dict:
    return {"teams": {str(team_id): {"scouts": scouts}}}


def _share(payload: object, skill: str = _SKILL, n: int = 400) -> dict[str | None, int]:
    # Empirical model split across many run ids — buckets are uniform, so shares track the config.
    counts: dict[str | None, int] = {}
    for i in range(n):
        model = _resolve(skill=skill, run_id=f"run-{i}", payload=payload)
        counts[model] = counts.get(model, 0) + 1
    return counts


class TestResolveScoutModel:
    @parameterized.expand(
        [
            ("no_payload", None),
            ("no_teams_key", {}),
            ("team_not_listed", {"teams": {"999": {"scouts": {_SKILL: {GLM_MODEL: 1}}}}}),
            ("scout_not_listed", _scouts({_OTHER_SKILL: {GLM_MODEL: 1}})),
            ("empty_distribution", _scouts({_SKILL: {}})),
        ]
    )
    def test_keeps_agent_default_when_unconfigured(self, _name: str, payload: object) -> None:
        assert _resolve(payload=payload) is None

    def test_full_weight_routes_every_run(self) -> None:
        assert _resolve(payload=_scouts({_SKILL: {GLM_MODEL: 1}})) == GLM_MODEL

    def test_locks_flag_key(self) -> None:
        with patch(_PAYLOAD_PATH, return_value=None) as mock_payload:
            resolve_scout_model(_fake_team(), _SKILL, _RUN_ID)
        assert mock_payload.call_args.args[0] == "scouts-model-selection"

    @parameterized.expand(
        [
            # A routed model must carry a runtime, else the agent server can't route it. Claude ids
            # infer `claude`; everything else (GLM, GPT — all OpenAI-compatible) infers `codex`.
            ("glm_infers_codex", GLM_MODEL, "codex"),
            ("gpt_infers_codex", _GPT, "codex"),
            ("claude_infers_claude", "claude-opus-4-8", "claude"),
        ]
    )
    def test_infers_runtime_from_model_id(self, _name: str, model: str, expected_adapter: str) -> None:
        assert _resolve_full(payload=_scouts({_SKILL: {model: 1}})) == ScoutModel(
            model=model, runtime_adapter=expected_adapter
        )

    def test_explicit_runtime_adapter_overrides_inference(self) -> None:
        # Object form pins the runtime explicitly, beating the id-based inference (which would say codex).
        resolved = _resolve_full(payload=_scouts({_SKILL: {GLM_MODEL: {"fraction": 1, "runtime_adapter": "claude"}}}))
        assert resolved == ScoutModel(model=GLM_MODEL, runtime_adapter="claude")

    @parameterized.expand(
        [
            # A bad runtime must not reach the run state — it'd blow up when cast to the RuntimeAdapter
            # enum downstream. Drop it and infer from the id instead. The unhashable cases (list/dict)
            # would also raise from the set-membership test if not guarded, failing the run.
            ("typo", "cluade"),
            ("non_string", 5),
            ("list", ["codex"]),
            ("dict", {"codex": 1}),
        ]
    )
    def test_bad_explicit_runtime_adapter_falls_back_to_inference(self, _name: str, bad_adapter: object) -> None:
        resolved = _resolve_full(
            payload=_scouts({_SKILL: {GLM_MODEL: {"fraction": 1, "runtime_adapter": bad_adapter}}})
        )
        assert resolved == ScoutModel(model=GLM_MODEL, runtime_adapter="codex")

    def test_object_form_drops_malformed_fraction(self) -> None:
        # A pinned runtime can't rescue a malformed fraction — the entry is dropped, agent default kept.
        resolved = _resolve_full(
            payload=_scouts({_SKILL: {GLM_MODEL: {"fraction": "lots", "runtime_adapter": "codex"}}})
        )
        assert resolved == ScoutModel(model=None, runtime_adapter=None)

    def test_named_default_remainder_infers_its_runtime(self) -> None:
        # The remainder model (named `default`) also gets a runtime inferred from its id. With no
        # fractional models, every run lands in the remainder, so this is deterministic.
        resolved = _resolve_full(payload=_scouts({_SKILL: {"default": GLM_MODEL}}))
        assert resolved == ScoutModel(model=GLM_MODEL, runtime_adapter="codex")

    def test_unconfigured_keeps_both_defaults(self) -> None:
        assert _resolve_full(payload=None) == ScoutModel(model=None, runtime_adapter=None)

    def test_each_team_gets_its_own_config(self) -> None:
        # One payload, two teams, different model per team — the whole point of the team key.
        payload = {
            "teams": {
                "2": {"scouts": {_SKILL: {GLM_MODEL: 1}}},
                "112495": {"scouts": {_SKILL: {_GPT: 1}}},
            }
        }
        assert _resolve(team=_fake_team(2), payload=payload) == GLM_MODEL
        assert _resolve(team=_fake_team(112495), payload=payload) == _GPT

    def test_child_env_resolves_via_parent_project_key(self) -> None:
        # A child env keyed by its parent project id still resolves.
        payload = _scouts({_SKILL: {GLM_MODEL: 1}}, team_id=2)
        child = _fake_team(team_id=555, parent_team_id=2)
        assert _resolve(team=child, payload=payload) == GLM_MODEL

    def test_team_wildcard_applies_to_unlisted_team(self) -> None:
        payload = {"teams": {"*": {"scouts": {_SKILL: {GLM_MODEL: 1}}}}}
        assert _resolve(team=_fake_team(999), payload=payload) == GLM_MODEL

    def test_scout_wildcard_applies_to_unlisted_scout(self) -> None:
        assert _resolve(skill=_OTHER_SKILL, payload=_scouts({"*": {GLM_MODEL: 1}})) == GLM_MODEL

    def test_named_default_takes_the_remainder(self) -> None:
        # 20% gpt, the remaining 80% pinned to a named default model (not the agent-server default).
        shares = _share(_scouts({_SKILL: {_GPT: 0.2, "default": GLM_MODEL}}))
        assert set(shares) == {_GPT, GLM_MODEL}
        assert None not in shares

    def test_multi_model_split_is_proportional(self) -> None:
        # 30% glm, 30% gpt, 40% agent-server default — all three buckets are non-trivially populated.
        shares = _share(_scouts({_SKILL: {GLM_MODEL: 0.3, _GPT: 0.3}}))
        assert shares.get(GLM_MODEL, 0) > 0
        assert shares.get(_GPT, 0) > 0
        assert shares.get(None, 0) > 0
        # The remainder (default) is the largest slice here (0.4 vs 0.3 each).
        assert shares[None] == max(shares.values())

    def test_selection_is_deterministic_per_run(self) -> None:
        # Full 50/50 split (no remainder) so every run resolves to a real model, then assert the
        # same run_id resolves the same model twice — the determinism guarantee, not None == None.
        payload = _scouts({_SKILL: {GLM_MODEL: 0.5, _GPT: 0.5}})
        first = _resolve(payload=payload)
        assert first in {GLM_MODEL, _GPT}
        assert first == _resolve(payload=payload)

    @parameterized.expand(
        [
            ("malformed_weight_dropped", {GLM_MODEL: "lots"}),
            ("zero_weight_dropped", {GLM_MODEL: 0}),
            ("bool_weight_dropped", {GLM_MODEL: True}),
        ]
    )
    def test_malformed_weights_keep_agent_default(self, _name: str, dist: dict) -> None:
        assert _resolve(payload=_scouts({_SKILL: dist})) is None

    def test_payload_read_failure_keeps_agent_default(self) -> None:
        # A scout must never fail to run because the gate was unreachable — fall back to the default.
        with patch(_PAYLOAD_PATH, side_effect=RuntimeError("flag service down")):
            assert resolve_scout_model(_fake_team(), _SKILL, _RUN_ID) == ScoutModel(model=None, runtime_adapter=None)
