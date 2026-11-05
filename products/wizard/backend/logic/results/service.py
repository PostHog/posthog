from uuid import UUID

from django.utils import timezone

from products.dashboards.backend.facade import api as dashboards_facade
from products.notebooks.backend.facade import api as notebooks_facade
from products.product_analytics.backend.facade import api as product_analytics_facade
from products.wizard.backend.facade.contracts import WizardRunDTO, WizardSpendProjection, WizardSpendProjectionItem
from products.wizard.backend.facade.enums import WizardSpendCurrency, WizardSpendFixLocation
from products.wizard.backend.logic.artifacts import store as artifact_store
from products.wizard.backend.logic.results.billing import get_organization_billing
from products.wizard.backend.logic.results.parser import InvalidProgramResultError, ProgramResult, parse_program_result
from products.wizard.backend.logic.results.pricing import UnpriceableBillingError, price_savings
from products.wizard.backend.logic.runs import store as run_store
from products.wizard.backend.observability.service import wizard_observability


def record_program_result(team_id: int, run_id: UUID, raw: bytes | None, *, has_pull_request: bool) -> None:
    """Stores what the agent reported in its result file as run artifacts.

    A run without a result file, or with one that fails a check, still completes: the pull request stands
    on its own. The projection is stored only when every check passes and the savings can be priced.
    """
    if not raw:
        return

    run = run_store.get_run(team_id, run_id)

    try:
        result = parse_program_result(raw)
        _check_ownership(team_id, result)
    except InvalidProgramResultError as error:
        wizard_observability.program_result_rejected(run, reason=str(error))
        return

    notebook = artifact_store.upsert_notebook(
        team_id=team_id,
        run_id=run.id,
        short_id=result.notebook_short_id,
        dashboard_ids=result.dashboard_ids,
        insight_ids=result.insight_ids,
    )
    wizard_observability.artifact_created(run, notebook)

    projection = _price_projection(run, result, has_pull_request=has_pull_request)
    if projection is None:
        return

    stored = artifact_store.upsert_spend_projection(team_id=team_id, run_id=run.id, projection=projection)
    wizard_observability.artifact_created(run, stored)


def _check_ownership(team_id: int, result: ProgramResult) -> None:
    if not notebooks_facade.notebook_exists(team_id, result.notebook_short_id, include_deleted=False):
        raise InvalidProgramResultError("The notebook is not in this project")
    if dashboards_facade.unknown_dashboard_ids(result.dashboard_ids, team_id=team_id):
        raise InvalidProgramResultError("A dashboard is not in this project")
    if product_analytics_facade.unknown_insight_ids(result.insight_ids, team_id=team_id):
        raise InvalidProgramResultError("An insight is not in this project")


def _price_projection(
    run: WizardRunDTO, result: ProgramResult, *, has_pull_request: bool
) -> WizardSpendProjection | None:
    if not has_pull_request and any(claim.fixed_in == WizardSpendFixLocation.PULL_REQUEST for claim in result.savings):
        wizard_observability.spend_projection_dropped(run, reason="pull_request_missing")
        return None

    billing = get_organization_billing(run.team_id)
    if billing is None:
        wizard_observability.spend_projection_dropped(run, reason="billing_unavailable")
        return None

    try:
        priced = price_savings(billing, result.savings)
    except UnpriceableBillingError as error:
        wizard_observability.spend_projection_dropped(run, reason=str(error))
        return None

    return WizardSpendProjection(
        currency=WizardSpendCurrency.USD,
        baseline_monthly=priced.baseline_monthly,
        saving_monthly=priced.saving_monthly,
        items=tuple(
            WizardSpendProjectionItem(
                id=entry.claim.id,
                title=entry.claim.title,
                billing_type=entry.claim.billing_type,
                unit=entry.claim.unit,
                volume_before=entry.claim.volume_before,
                volume_after=entry.claim.volume_after,
                saving_monthly=entry.saving_monthly,
                evidence=entry.claim.evidence,
                tradeoff=entry.claim.tradeoff,
                effort=entry.claim.effort,
                fixed_in=entry.claim.fixed_in,
            )
            for entry in sorted(priced.claims, key=lambda entry: entry.saving_monthly.high, reverse=True)
        ),
        priced_at=timezone.now(),
    )
