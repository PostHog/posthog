from datetime import datetime
from typing import Any

from products.wizard.backend.facade.contracts import (
    WizardRunArtifactDTO,
    WizardRunGitDiffArtifactDTO,
    WizardRunNotebookArtifactDTO,
    WizardRunPullRequestArtifactDTO,
    WizardRunSpendProjectionArtifactDTO,
    WizardSpendProjection,
    WizardSpendProjectionItem,
    WizardSpendRange,
)
from products.wizard.backend.facade.enums import (
    WizardRunArtifactType,
    WizardSpendCurrency,
    WizardSpendEffort,
    WizardSpendFixLocation,
)
from products.wizard.backend.models import WizardRunArtifact


def record_to_artifact(artifact: WizardRunArtifact) -> WizardRunArtifactDTO:
    artifact_type = WizardRunArtifactType(artifact.type)

    if artifact_type == WizardRunArtifactType.NOTEBOOK:
        return _record_to_notebook(artifact)

    if artifact_type == WizardRunArtifactType.SPEND_PROJECTION:
        return _record_to_spend_projection(artifact)

    if artifact_type == WizardRunArtifactType.GIT_DIFF:
        if artifact.size_bytes is None or artifact.content_hash is None:
            raise ValueError("Git diff artifact is missing stored content metadata.")

        metadata = artifact.metadata or {}
        additions = metadata.get("additions")
        removals = metadata.get("removals")

        return WizardRunGitDiffArtifactDTO(
            id=artifact.id,
            team_id=artifact.team_id,
            run_id=artifact.run_id,
            artifact_type=WizardRunArtifactType.GIT_DIFF,
            size_bytes=artifact.size_bytes,
            content_hash=artifact.content_hash,
            additions=additions if isinstance(additions, int) else None,
            removals=removals if isinstance(removals, int) else None,
            created_at=artifact.created_at,
        )

    metadata = artifact.metadata or {}
    number = metadata.get("number")
    repository = metadata.get("repository")
    head_branch = metadata.get("head_branch")
    base_branch = metadata.get("base_branch")

    if (
        artifact.external_url is None
        or not isinstance(number, int)
        or not isinstance(repository, str)
        or not isinstance(head_branch, str)
        or not isinstance(base_branch, str)
    ):
        raise ValueError("Pull request artifact is missing repository metadata.")

    return WizardRunPullRequestArtifactDTO(
        id=artifact.id,
        team_id=artifact.team_id,
        run_id=artifact.run_id,
        artifact_type=WizardRunArtifactType.PULL_REQUEST,
        url=artifact.external_url,
        number=number,
        repository=repository,
        head_branch=head_branch,
        base_branch=base_branch,
        created_at=artifact.created_at,
    )


def pull_request_metadata_to_record(
    number: int, repository: str, head_branch: str, base_branch: str
) -> dict[str, object]:
    return {
        "number": number,
        "repository": repository,
        "head_branch": head_branch,
        "base_branch": base_branch,
    }


def notebook_metadata_to_record(
    short_id: str, dashboard_ids: tuple[int, ...], insight_ids: tuple[int, ...]
) -> dict[str, object]:
    return {"short_id": short_id, "dashboard_ids": list(dashboard_ids), "insight_ids": list(insight_ids)}


def spend_projection_metadata_to_record(projection: WizardSpendProjection) -> dict[str, object]:
    return {
        "currency": projection.currency.value,
        "baseline_monthly": projection.baseline_monthly,
        "saving_monthly": _range_to_record(projection.saving_monthly),
        "priced_at": projection.priced_at.isoformat(),
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "billing_type": item.billing_type,
                "unit": item.unit,
                "volume_before": item.volume_before,
                "volume_after": _range_to_record(item.volume_after),
                "saving_monthly": _range_to_record(item.saving_monthly),
                "evidence": item.evidence,
                "tradeoff": item.tradeoff,
                "effort": item.effort.value,
                "fixed_in": item.fixed_in.value,
            }
            for item in projection.items
        ],
    }


def _record_to_notebook(artifact: WizardRunArtifact) -> WizardRunNotebookArtifactDTO:
    metadata = artifact.metadata or {}
    short_id = metadata.get("short_id")
    dashboard_ids = metadata.get("dashboard_ids")
    insight_ids = metadata.get("insight_ids")

    if not isinstance(short_id, str) or not isinstance(dashboard_ids, list) or not isinstance(insight_ids, list):
        raise ValueError("Notebook artifact is missing its metadata.")

    return WizardRunNotebookArtifactDTO(
        id=artifact.id,
        team_id=artifact.team_id,
        run_id=artifact.run_id,
        artifact_type=WizardRunArtifactType.NOTEBOOK,
        short_id=short_id,
        dashboard_ids=tuple(int(value) for value in dashboard_ids),
        insight_ids=tuple(int(value) for value in insight_ids),
        created_at=artifact.created_at,
    )


def _record_to_spend_projection(artifact: WizardRunArtifact) -> WizardRunSpendProjectionArtifactDTO:
    metadata: dict[str, Any] = artifact.metadata or {}

    try:
        return WizardRunSpendProjectionArtifactDTO(
            id=artifact.id,
            team_id=artifact.team_id,
            run_id=artifact.run_id,
            artifact_type=WizardRunArtifactType.SPEND_PROJECTION,
            currency=WizardSpendCurrency(metadata.get("currency", WizardSpendCurrency.USD.value)),
            baseline_monthly=float(metadata["baseline_monthly"]),
            saving_monthly=_range_from_record(metadata["saving_monthly"]),
            priced_at=datetime.fromisoformat(metadata["priced_at"]),
            items=tuple(
                WizardSpendProjectionItem(
                    id=item["id"],
                    title=item["title"],
                    billing_type=item["billing_type"],
                    unit=item["unit"],
                    volume_before=float(item["volume_before"]),
                    volume_after=_range_from_record(item["volume_after"]),
                    saving_monthly=_range_from_record(item["saving_monthly"]),
                    evidence=item["evidence"],
                    tradeoff=item["tradeoff"],
                    effort=WizardSpendEffort(item["effort"]),
                    fixed_in=WizardSpendFixLocation(item["fixed_in"]),
                )
                for item in metadata["items"]
            ),
            created_at=artifact.created_at,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Spend projection artifact has invalid metadata.") from error


def _range_to_record(value: WizardSpendRange) -> dict[str, float]:
    return {"low": value.low, "high": value.high}


def _range_from_record(value: Any) -> WizardSpendRange:
    return WizardSpendRange(low=float(value["low"]), high=float(value["high"]))
