from pathlib import Path
from uuid import UUID

import pytest
from unittest.mock import Mock, patch

from products.posthog_ai.eval_harness.base import _BaseEvalRun
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.discovery import discover_suites
from products.posthog_ai.eval_harness.harness.requirements import SuiteKind


@pytest.mark.asyncio
async def test_discovered_suites_match_reporting_enrollment(tmp_path: Path) -> None:
    ctx = Mock(spec=EvalContext, posthog_client=None, case_filter=None, skill_delivery="bundled")
    ctx.engine = Mock()
    ctx.provider_strategy = Mock()
    ctx.demo_data = Mock()
    ctx.sandbox_slots = Mock()
    runs: list[_BaseEvalRun] = []

    async def capture(run: _BaseEvalRun) -> None:
        runs.append(run)

    suites = discover_suites()
    assert suites
    keys: set[str] = set()
    with (
        patch.object(_BaseEvalRun, "run", capture),
        patch("products.posthog_ai.eval_harness.base.build_case_dir", return_value=tmp_path),
        patch("products.posthog_ai.evals.taxonomic_filter.eval_search_intent.system_one_configured", return_value=True),
        patch("products.posthog_ai.evals.taxonomic_filter.eval_search_intent.fetch_search_intent_prompt"),
    ):
        for suite in suites:
            runs.clear()
            await suite.fn(ctx)
            assert len(runs) == 1, suite.id
            run = runs[0]
            config = run.offline_suite
            assert config is not None, suite.id
            assert run.send_to_posthog, suite.id
            assert config.key == suite.id
            assert config.key not in keys
            keys.add(config.key)
            assert config.project_id == 2
            metrics = {scorer._name() for scorer in run.active_scorers}
            assert set(config.scorer_kinds) == set(config.scorer_versions) == metrics, suite.id
            assert len(set(config.scorer_versions.values())) == len(metrics), suite.id
            assert all(isinstance(version, UUID) and version.int for version in config.scorer_versions.values())
            assert ("exit_code_zero" in metrics) == (suite.kind == SuiteKind.SANDBOXED), suite.id
            assert any(tag.startswith("team:") for tag in config.tags), suite.id
            assert any(tag.startswith("component:") for tag in config.tags), suite.id
