"""The analytics events every skill write reports, and the properties they carry."""

from typing import Any

import structlog
from rest_framework.request import Request

from posthog.event_usage import report_user_action
from posthog.models import Team, User

from ..models.skills import LLMSkill

logger = structlog.get_logger(__name__)


def record_skill_event(
    *,
    log_event: str,
    action: str,
    user: User,
    team: Team,
    request: Request,
    props: dict[str, Any],
) -> None:
    """Log a skill write and report it as a product event, with the same properties on both."""
    logger.info(log_event, team_id=team.id, user_id=user.id, **props)
    report_user_action(user, action, props, team=team, request=request)


def file_extension(path: str) -> str:
    return path.rsplit(".", 1)[1].lower() if "." in path else ""


def skill_analytics_props(skill: LLMSkill) -> dict[str, Any]:
    """Properties shared by every skill report_user_action event.

    These power the internal LLMA skills adoption/usage dashboards — keep stable
    and additive (renaming a key here will rename it on every dashboard).
    """
    file_count = skill.files.count() if skill.pk else 0
    body = skill.body or ""
    description = skill.description or ""
    allowed_tools = skill.allowed_tools or []
    return {
        "skill_id": str(skill.id),
        "skill_name": skill.name,
        "skill_version": skill.version,
        "skill_is_latest": skill.is_latest,
        "skill_body_length": len(body),
        "skill_description_length": len(description),
        "skill_file_count": file_count,
        "skill_has_files": file_count > 0,
        "skill_has_license": bool(skill.license),
        "skill_has_compatibility": bool(skill.compatibility),
        "skill_has_allowed_tools": bool(allowed_tools),
        "skill_allowed_tools_count": len(allowed_tools),
    }


def publish_analytics_props(
    published_skill: LLMSkill, validated_data: dict[str, Any], *, owners_changed: bool
) -> dict[str, Any]:
    """Which parts of a publish the caller actually sent, alongside the new version's own properties."""
    edits_value = validated_data.get("edits")
    file_edits_value = validated_data.get("file_edits")
    files_value = validated_data.get("files")
    return {
        **skill_analytics_props(published_skill),
        "base_version": validated_data["base_version"],
        "body_changed": validated_data.get("body") is not None or edits_value is not None,
        "files_replaced": files_value is not None,
        "files_replaced_count": len(files_value) if files_value is not None else 0,
        "edits_used": edits_value is not None,
        "edits_count": len(edits_value) if edits_value is not None else 0,
        "file_edits_used": file_edits_value is not None,
        "file_edits_count": len(file_edits_value) if file_edits_value is not None else 0,
        "description_changed": validated_data.get("description") is not None,
        "license_changed": validated_data.get("license") is not None,
        "compatibility_changed": validated_data.get("compatibility") is not None,
        "allowed_tools_changed": validated_data.get("allowed_tools") is not None,
        "metadata_changed": validated_data.get("metadata") is not None,
        "owners_changed": owners_changed,
        "version_description_set": validated_data.get("version_description") is not None,
    }
