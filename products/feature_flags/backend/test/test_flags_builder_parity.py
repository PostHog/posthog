"""Python half of the flags-cache builder parity test.

Seeds one team from rust/feature-flags/tests/fixtures/builder_parity_seed.json, builds the
hypercache payload, and asserts it against builder_parity_golden.json. The Rust half
(rust/feature-flags/tests/flags_builder_parity.rs) seeds the same rows and asserts the same
golden, so the golden is the only place the two builders meet.

Neither half writes the golden during a normal run. Regeneration is explicit:

    UPDATE_FLAGS_BUILDER_PARITY_GOLDEN=1 hogli test \
        products/feature_flags/backend/test/test_flags_builder_parity.py
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest

from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.flags_cache import _get_feature_flags_for_service
from products.feature_flags.backend.models.evaluation_context import EvaluationContext, FeatureFlagEvaluationContext
from products.feature_flags.backend.models.feature_flag import FeatureFlag

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FIXTURE_DIR = _REPO_ROOT / "rust" / "feature-flags" / "tests" / "fixtures"
SEED_PATH = _FIXTURE_DIR / "builder_parity_seed.json"
GOLDEN_PATH = _FIXTURE_DIR / "builder_parity_golden.json"

REGENERATE_ENV_VAR = "UPDATE_FLAGS_BUILDER_PARITY_GOLDEN"
REGENERATE_COMMAND = (
    f"{REGENERATE_ENV_VAR}=1 hogli test products/feature_flags/backend/test/test_flags_builder_parity.py"
)

_TEAM_TOKEN = "@team"
_COHORT_PREFIX = "@cohort:"
_FLAG_PREFIX = "@flag:"
_FLAG_STR_PREFIX = "@flag_str:"


class _SeededIds:
    def __init__(self) -> None:
        self.team_id: int | None = None
        self.cohorts: dict[str, int] = {}
        self.flags: dict[str, int] = {}

    def _id_for(self, token: str) -> int | None:
        if token == _TEAM_TOKEN:
            assert self.team_id is not None, "team must be seeded before any token is resolved"
            return self.team_id
        for prefix, table in (
            (_COHORT_PREFIX, self.cohorts),
            (_FLAG_PREFIX, self.flags),
            (_FLAG_STR_PREFIX, self.flags),
        ):
            if token.startswith(prefix):
                ref = token[len(prefix) :]
                if ref not in table:
                    raise KeyError(f"{token} refers to a ref that {SEED_PATH.name} does not define before this point")
                return table[ref]
        return None

    def resolve_scalar(self, value: str) -> Any:
        seeded_id = self._id_for(value)
        if seeded_id is None:
            return value
        return str(seeded_id) if value.startswith(_FLAG_STR_PREFIX) else seeded_id

    def resolve_key(self, key: str) -> str:
        seeded_id = self._id_for(key)
        return key if seeded_id is None else str(seeded_id)


def resolve_tokens(value: Any, ids: _SeededIds) -> Any:
    if isinstance(value, dict):
        return {ids.resolve_key(k): resolve_tokens(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_tokens(v, ids) for v in value]
    if isinstance(value, str):
        return ids.resolve_scalar(value)
    return value


def _tokenize_property_leaves(value: Any, flag_tokens: dict[int, str], cohort_tokens: dict[int, str]) -> Any:
    """Rewrite the flag and cohort ids buried in a filter tree back into seed tokens.

    Flag and cohort references share one leaf shape across flag filters and cohort filters, so
    the same walk covers both. Ids that no seed ref owns (a deliberately missing dependency)
    are left alone.
    """
    if isinstance(value, list):
        return [_tokenize_property_leaves(v, flag_tokens, cohort_tokens) for v in value]
    if not isinstance(value, dict):
        return value

    result = {k: _tokenize_property_leaves(v, flag_tokens, cohort_tokens) for k, v in value.items()}
    if result.get("type") == "flag":
        token = _token_for(flag_tokens, result.get("key"))
        if token is not None:
            result["key"] = token.replace(_FLAG_PREFIX, _FLAG_STR_PREFIX)
    elif result.get("type") == "cohort":
        token = _token_for(cohort_tokens, result.get("value"))
        if token is not None:
            result["value"] = token
    return result


def tokenize_payload(payload: dict[str, Any], ids: _SeededIds) -> dict[str, Any]:
    """Rewrite a built payload's real ids back into seed tokens.

    Structural rather than a blind search for the id values, because a seeded id can also be a
    rollout percentage or a count. A spot this misses leaves a raw id in the golden, which the
    next run against a different team fails on.
    """
    flag_tokens = {flag_id: f"{_FLAG_PREFIX}{ref}" for ref, flag_id in ids.flags.items()}
    cohort_tokens = {cohort_id: f"{_COHORT_PREFIX}{ref}" for ref, cohort_id in ids.cohorts.items()}

    def flag_ref(flag_id: int) -> Any:
        return flag_tokens.get(flag_id, flag_id)

    flags = []
    for flag in payload["flags"]:
        entry = _tokenize_property_leaves(flag, flag_tokens, cohort_tokens)
        entry["id"] = flag_ref(flag["id"])
        entry["team_id"] = _TEAM_TOKEN
        flags.append(entry)

    cohorts = []
    for cohort in payload["cohorts"]:
        entry = _tokenize_property_leaves(cohort, flag_tokens, cohort_tokens)
        entry["id"] = cohort_tokens.get(cohort["id"], cohort["id"])
        entry["team_id"] = _TEAM_TOKEN
        cohorts.append(entry)

    metadata = payload["evaluation_metadata"]
    return {
        "flags": flags,
        "evaluation_metadata": {
            "dependency_stages": [[flag_ref(i) for i in stage] for stage in metadata["dependency_stages"]],
            "flags_with_missing_deps": [flag_ref(i) for i in metadata["flags_with_missing_deps"]],
            "transitive_deps": {
                str(flag_ref(int(k))): [flag_ref(i) for i in v] for k, v in metadata["transitive_deps"].items()
            },
        },
        "cohorts": cohorts,
    }


def order_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Sort the two id-keyed arrays.

    Neither builder promises an order for them: Python takes whatever the queryset returns and
    Rust sorts cohorts but not flags. The shadow diff both sides share matches by id for the
    same reason, so an order neither builder guarantees must not be part of the golden.
    """
    return {
        "flags": sorted(payload["flags"], key=lambda flag: flag["id"]),
        "evaluation_metadata": payload["evaluation_metadata"],
        "cohorts": sorted(payload["cohorts"], key=lambda cohort: cohort["id"]),
    }


class TestFlagsBuilderParity(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.seed = json.loads(SEED_PATH.read_text())
        self.ids = _SeededIds()
        self.ids.team_id = self.team.id
        self._seed_cohorts()
        self._seed_flags()

    def _seed_cohorts(self) -> None:
        for spec in self.seed["cohorts"]:
            cohort = Cohort.objects.create(
                team=self.team,
                created_by=None,
                name=spec["name"],
                description=spec["description"],
                deleted=spec["deleted"],
                filters=resolve_tokens(spec["filters"], self.ids),
                query=spec["query"],
                version=spec["version"],
                pending_version=spec["pending_version"],
                count=spec["count"],
                is_calculating=spec["is_calculating"],
                is_static=spec["is_static"],
                errors_calculating=spec["errors_calculating"],
                groups=spec["groups"],
                cohort_type=spec["cohort_type"],
                last_backfill_person_properties_at=_parse_timestamp(spec["last_backfill_person_properties_at"]),
                last_backfill_events_at=_parse_timestamp(spec["last_backfill_events_at"]),
                last_realtime_cohort_calculation_at=_parse_timestamp(spec["last_realtime_cohort_calculation_at"]),
            )
            self.ids.cohorts[spec["ref"]] = cohort.id
            # Django derives this column on save, so only the seed file can state it for the
            # Rust seeder, which writes the row with raw SQL. Both seeders must plant the same
            # bytes or the two payloads differ before either builder runs.
            assert cohort.condition_type == spec["condition_type"], (
                f"Cohort {spec['ref']} was seeded with condition_type {cohort.condition_type!r}, but "
                f"{SEED_PATH.name} states {spec['condition_type']!r}. Django computes this column from "
                f"the cohort's filters, so update the seed to match and regenerate the golden:\n"
                f"    {REGENERATE_COMMAND}"
            )

    def _seed_flags(self) -> None:
        for spec in self.seed["flags"]:
            flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=None,
                key=spec["key"],
                name=spec["name"],
                active=spec["active"],
                deleted=spec["deleted"],
                ensure_experience_continuity=spec["ensure_experience_continuity"],
                version=spec["version"],
                evaluation_runtime=spec["evaluation_runtime"],
                bucketing_identifier=spec["bucketing_identifier"],
                filters=resolve_tokens(spec["filters"], self.ids),
            )
            self.ids.flags[spec["ref"]] = flag.id

            for context_name in spec["evaluation_contexts"]:
                context, _ = EvaluationContext.objects.get_or_create(team=self.team, name=context_name)
                FeatureFlagEvaluationContext.objects.create(feature_flag=flag, evaluation_context=context)

            if spec["has_experiment"]:
                Experiment.objects.create(team=self.team, name=f"{spec['key']} experiment", feature_flag=flag)

    def test_payload_matches_golden(self) -> None:
        built = order_payload(_get_feature_flags_for_service(self.team))

        if os.environ.get(REGENERATE_ENV_VAR):
            GOLDEN_PATH.write_text(json.dumps(tokenize_payload(built, self.ids), indent=4) + "\n")
            self.fail(
                f"Regenerated {GOLDEN_PATH.relative_to(_REPO_ROOT)} from this run. Review the diff, then rerun "
                f"without {REGENERATE_ENV_VAR} set, and rerun the Rust half:\n"
                f"    SQLX_OFFLINE=true cargo test -p feature-flags --test flags_builder_parity"
            )

        expected = order_payload(resolve_tokens(json.loads(GOLDEN_PATH.read_text()), self.ids))

        assert built == expected, (
            "The Python flags-cache builder no longer produces the golden payload.\n\n"
            "The Rust builder asserts against the same file, so a change here that is correct is a "
            "change both builders have to make. Confirm the new payload is what you meant to ship, then:\n"
            f"    1. Regenerate {GOLDEN_PATH.relative_to(_REPO_ROOT)}:\n"
            f"       {REGENERATE_COMMAND}\n"
            "    2. Rerun the Rust half against it:\n"
            "       SQLX_OFFLINE=true cargo test -p feature-flags --test flags_builder_parity"
        )


def _parse_timestamp(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _token_for(tokens: dict[int, str], value: Any) -> str | None:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    return tokens.get(numeric)
