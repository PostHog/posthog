from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from django.conf import settings
from django.db import transaction

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.rubrics import ScoutRubricReferenceContext, ScoutRubricState
from products.signals.backend.scout_harness.trial_rubrics import SavedScoutRubricReader
from products.signals.evals.agentic.rubric_session import RubricSnapshot

if TYPE_CHECKING:
    from products.signals.evals.agentic.saved_case import SavedScoutCase


def _session_reference(snapshot: RubricSnapshot) -> ScoutRubricReferenceContext:
    source_bundle = snapshot.document.generation.get("source_bundle")
    if not isinstance(source_bundle, dict) or not isinstance(source_bundle.get("scout_context"), dict):
        raise ValueError("The session rubric has no captured generator reference")
    scout_context = source_bundle["scout_context"]
    assert isinstance(scout_context, dict)
    return ScoutRubricReferenceContext.model_validate(
        {
            **{
                key: scout_context[key]
                for key in (
                    "skill_name",
                    "skill_version",
                    "description",
                    "instructions",
                    "instructions_truncated",
                    "report_channel",
                    "report_disposition_instructions",
                    "reference_files",
                    "reference_files_truncated",
                )
                if key in scout_context
            },
            "skill_id": f"offline-session-rubric:{snapshot.sha256}",
            "reference_texts": source_bundle.get("reference_texts"),
            "reference_limits": source_bundle.get("reference_limits"),
        }
    )


def validate_session_rubric_time_shift(
    saved: SavedScoutCase, snapshot: RubricSnapshot, target_cutoff: datetime
) -> None:
    if not saved._delta(target_cutoff):
        return
    replacements = {
        source: target
        for source, target in saved.text_replacements(target_cutoff).items()
        if source in saved.manifest.time_strings and source != target
    }
    if not replacements:
        return
    reference = _session_reference(snapshot)
    content = {
        "reference.description": reference.description,
        "reference.instructions": reference.instructions,
        "reference.report_disposition_instructions": reference.report_disposition_instructions,
        **{
            f"reference.reference_texts[{index}].content": text.content
            for index, text in enumerate(reference.reference_texts)
        },
    }
    for index, criterion in enumerate(snapshot.document.criteria):
        if criterion.enabled:
            content.update(
                {
                    f"criteria[{index}].title": criterion.title,
                    f"criteria[{index}].description": criterion.description,
                    f"criteria[{index}].pass_condition": criterion.pass_condition,
                    f"criteria[{index}].applicability": criterion.applicability,
                }
            )
    for field, text in content.items():
        if saved._replace_text(text, replacements) != text:
            raise ValueError(
                f"The dataset shift from {saved.manifest.source_cutoff.isoformat()} to {target_cutoff.isoformat()} "
                f"would change frozen rubric {field}. Shifted reference dates are not supported by the comparison judge."
            )


def install_session_rubric(config: SignalScoutConfig, snapshot: RubricSnapshot) -> None:
    if settings.TEST is not True or settings.DEBUG is not True:
        raise RuntimeError("Installing an offline session rubric requires TEST and DEBUG")
    if snapshot.document.scout_name != config.skill_name:
        raise ValueError("The session rubric does not belong to this scout")
    reference = _session_reference(snapshot)
    state = ScoutRubricState(
        revision=1,
        criteria=snapshot.document.criteria,
        reference_context=reference,
        reference_generation_id=str(uuid5(NAMESPACE_URL, f"posthog:offline-session-rubric:{snapshot.sha256}")),
    )
    previous = config.rubrics
    try:
        with transaction.atomic():
            config.rubrics = {
                **state.model_dump(mode="json"),
                "offline_session_rubric": {"sha256": snapshot.sha256, "path": str(snapshot.path)},
            }
            config.save(update_fields=["rubrics", "updated_at"])
            # Apply the production completeness checks before committing the imported rubric.
            SavedScoutRubricReader(team_id=config.team_id).read(config_id=config.id, skill_name=config.skill_name)
    except Exception:
        config.rubrics = previous
        raise
