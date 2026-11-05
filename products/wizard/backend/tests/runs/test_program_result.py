import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models import Team

from products.notebooks.backend.facade import api as notebooks_facade
from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import (
    LocalFolderWorkspace,
    WizardRunDTO,
    WizardRunNotebookArtifactDTO,
    WizardRunSpendProjectionArtifactDTO,
    WizardSpendRange,
)
from products.wizard.backend.facade.enums import WizardRunEnvironment, WizardRunStatus
from products.wizard.backend.logic.registry.config import FALLBACK_REGISTRY
from products.wizard.backend.logic.results.parser import InvalidProgramResultError, parse_program_result
from products.wizard.backend.logic.results.pricing import _tiers, price_savings, price_usage
from products.wizard.backend.logic.runs import store as run_store
from products.wizard.backend.presentation.artifacts.serializers import serialize_wizard_run_artifact

TIERS = [
    {"unit_amount_usd": "0", "flat_amount_usd": "0", "up_to": 1000},
    {"unit_amount_usd": "0.01", "flat_amount_usd": "0", "up_to": 10000},
    {"unit_amount_usd": "0.005", "flat_amount_usd": "0", "up_to": None},
]


def _billing(**product: Any) -> dict[str, Any]:
    return {
        "projected_total_amount_usd": "140.00",
        "discount_percent": 0,
        "products": [
            {"type": "session_replay", "usage_key": "recordings", "tiers": TIERS, "projected_usage": 20000} | product
        ],
    }


def _saving(saving_id: str = "replay-sampling", *, before: int = 20000, low: int = 10000, high: int = 10000) -> dict:
    return {
        "id": saving_id,
        "title": "Record half of the sessions",
        "billing_type": "session_replay",
        "unit": "recordings",
        "before": before,
        "after": {"low": low, "high": high},
        "evidence": "Half of the recordings are under 10 seconds",
        "tradeoff": "Fewer replays for support",
        "effort": "setting",
        "fixed_in": "notebook",
    }


def _result(**fields: Any) -> bytes:
    return json.dumps(
        {"version": 1, "notebook_short_id": "abc123", "dashboard_ids": [], "insight_ids": [], "savings": []} | fields
    ).encode()


@parameterized.expand(
    [
        ("inside_free_tier", 500, [TIERS], 0, 0.0),
        ("across_two_tiers", 5000, [TIERS], 0, 40.0),
        ("into_the_last_tier", 20000, [TIERS], 0, 140.0),
        ("with_discount", 20000, [TIERS], 20, 112.0),
        (
            "with_addon_tiers",
            20000,
            [
                TIERS,
                [
                    {"unit_amount_usd": "0", "up_to": 1000},
                    {"unit_amount_usd": "0.002", "up_to": 10000},
                    {"unit_amount_usd": "0.001", "up_to": None},
                ],
            ],
            0,
            168.0,
        ),
    ]
)
def test_price_usage_matches_frontend_graduated_pricing(
    _name: str, usage: int, tiers: list, discount: float, expected: float
) -> None:
    assert price_usage(usage, [_tiers(entry) for entry in tiers], discount) == pytest.approx(expected)


def test_savings_are_priced_at_the_margin_and_combined_per_product() -> None:
    claims = parse_program_result(
        _result(savings=[_saving("a", low=14000, high=14000), _saving("b", low=14000, high=14000)])
    ).savings

    priced = price_savings(_billing(), claims)

    # 6,000 recordings off 20,000 all fall in the 0.005 tier, not the 0.007 average.
    assert [entry.saving_monthly for entry in priced.claims] == [
        WizardSpendRange(low=30, high=30),
        WizardSpendRange(low=30, high=30),
    ]
    # Together they remove 12,000, which reaches into the 0.01 tier.
    assert priced.saving_monthly == WizardSpendRange(low=70, high=70)
    assert priced.baseline_monthly == 140.0


@parameterized.expand(
    [
        ("unknown_field", _result(extra=True)),
        ("unsupported_version", _result(version=2)),
        ("volume_goes_up", _result(savings=[_saving(before=100, low=50, high=150)])),
        ("boolean_volume", _result(savings=[_saving() | {"before": True}])),
        ("duplicate_saving_ids", _result(savings=[_saving("a"), _saving("a")])),
        ("unknown_effort", _result(savings=[_saving() | {"effort": "magic"}])),
        ("not_json", b"{nope"),
    ]
)
def test_parse_program_result_rejects_invalid_files(_name: str, raw: bytes) -> None:
    with pytest.raises(InvalidProgramResultError):
        parse_program_result(raw)


def _create_run(team_id: int, user_id: int) -> WizardRunDTO:
    return run_store.create_run(
        team_id=team_id,
        created_by_id=user_id,
        environment=WizardRunEnvironment.LOCAL,
        workspace=LocalFolderWorkspace(project_name="example-project"),
        program=FALLBACK_REGISTRY.programs[0],
        status=WizardRunStatus.RUNNING,
    ).run


def _billing_service(billing: dict[str, Any] | None):
    license = MagicMock(is_v2_license=True)
    return (
        patch("products.wizard.backend.logic.results.billing.get_cached_instance_license", return_value=license),
        patch("products.wizard.backend.logic.results.billing.BillingManager.get_billing", return_value=billing),
    )


@pytest.mark.django_db
def test_record_program_result_stores_notebook_and_priced_projection(team, user) -> None:
    run = _create_run(team.id, user.id)
    notebook = notebooks_facade.create_notebook(team.id, title="Spend audit", content=None)
    license_patch, billing_patch = _billing_service(_billing())

    with license_patch, billing_patch:
        wizard_facade.record_program_result(
            team.id,
            run.id,
            _result(notebook_short_id=notebook.short_id, savings=[_saving()]),
            has_pull_request=False,
        )

    stored = {type(artifact): artifact for artifact in wizard_facade.list_run_artifacts(team.id, run.id)}
    assert stored[WizardRunNotebookArtifactDTO].short_id == notebook.short_id
    projection = stored[WizardRunSpendProjectionArtifactDTO]
    assert projection.saving_monthly == WizardSpendRange(low=50, high=50)
    assert serialize_wizard_run_artifact(projection)["items"][0]["saving_monthly"] == {"low": 50.0, "high": 50.0}


@pytest.mark.parametrize(
    "notebook_in_other_project,fixed_in,billing,keeps_notebook",
    [
        pytest.param(True, "notebook", _billing(), False, id="notebook_in_another_project"),
        pytest.param(False, "pr", _billing(), True, id="pr_saving_without_pull_request"),
        pytest.param(False, "notebook", None, True, id="billing_unavailable"),
        pytest.param(False, "notebook", _billing(type="product_analytics"), True, id="saving_on_unbilled_product"),
    ],
)
@pytest.mark.django_db
def test_record_program_result_stores_nothing_unchecked(
    team, user, notebook_in_other_project: bool, fixed_in: str, billing: dict | None, keeps_notebook: bool
) -> None:
    run = _create_run(team.id, user.id)
    owner = Team.objects.create(organization=team.organization, name="Other") if notebook_in_other_project else team
    notebook = notebooks_facade.create_notebook(owner.id, title="Spend audit", content=None)
    license_patch, billing_patch = _billing_service(billing)

    with license_patch, billing_patch:
        wizard_facade.record_program_result(
            team.id,
            run.id,
            _result(notebook_short_id=notebook.short_id, savings=[_saving() | {"fixed_in": fixed_in}]),
            has_pull_request=False,
        )

    stored_types = [type(artifact) for artifact in wizard_facade.list_run_artifacts(team.id, run.id)]
    assert stored_types == ([WizardRunNotebookArtifactDTO] if keeps_notebook else [])
