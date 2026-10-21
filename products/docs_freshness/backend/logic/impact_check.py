import re
import json
import uuid
import shlex
from typing import Any

from django.conf import settings
from django.core.cache import cache

import structlog

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration
from posthog.models.team import Team
from posthog.ph_client import ph_scoped_capture

from products.docs_freshness.backend.facade.contracts import (
    DocsFreshnessCheckError,
    MergeRefBehindHead,
    MergeRefMissing,
    PullRequestHead,
)
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.sandbox import SandboxBase, SandboxConfig, SandboxTemplate, get_sandbox_class

logger = structlog.get_logger(__name__)

CHECKED_REPOSITORY = "posthog/posthog"
DOCS_REPOSITORY = "posthog/posthog.com"
TOOL_REPOSITORY_URL = "https://github.com/PostHog/docs-freshness.git"
TOOL_DIRECTORY = "/tmp/docs-freshness"
CHECK_STDERR_PATH = "/tmp/docs-freshness-check.err"
PROMPT_PATH = f"{TOOL_DIRECTORY}/agents/linked-docs-pr.md"
CAPTURE_DISTINCT_ID = "docs-audit"
CHECKED_EVENT = "docs_impact_checked"
CHECKED_EVENT_UUID_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://github.com/PostHog/docs-freshness#docs_impact_checked"
)
CHECK_TIMEOUT_SECONDS = 15 * 60
PROMPT_TIMEOUT_SECONDS = 60
MAX_STDERR_CHARACTERS = 300
AGENT_STARTED_MARKER_TIMEOUT_SECONDS = 30 * 24 * 60 * 60

CLEAR_EXIT_CODE = 0
FLAGGED_EXIT_CODE = 1
MERGE_REF_BEHIND_HEAD_EXIT_CODE = 3
MERGE_REF_MISSING_EXIT_CODE = 4
GIT_LS_REMOTE_NO_MATCH_EXIT_CODE = 2
CHECKED_REPOSITORY_URL = "https://github.com/PostHog/posthog.git"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TOOL_REF_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._/-]*$")


@frozen
class DocsFreshnessSettings:
    team_id: int
    owner_user_id: int
    tool_ref: str


@frozen
class ImpactVerdict:
    impacted: tuple[dict[str, Any], ...]
    prompt_template: str | None = None

    @property
    def is_flagged(self) -> bool:
        return bool(self.impacted)


def configured_settings() -> DocsFreshnessSettings | None:
    team_id = settings.DOCS_FRESHNESS_TEAM_ID
    owner_user_id = settings.DOCS_FRESHNESS_OWNER_USER_ID
    tool_ref = settings.DOCS_FRESHNESS_TOOL_REF
    if team_id is None or owner_user_id is None or not tool_ref:
        return None
    if not _TOOL_REF_RE.fullmatch(tool_ref):
        logger.warning("docs_freshness: DOCS_FRESHNESS_TOOL_REF is not a plain git ref", tool_ref=tool_ref)
        return None
    return DocsFreshnessSettings(team_id=team_id, owner_user_id=owner_user_id, tool_ref=tool_ref)


def pull_request_url(head: PullRequestHead) -> str:
    return f"https://github.com/PostHog/posthog/pull/{head.pr_number}"


def check_pull_request_head(head: PullRequestHead) -> None:
    config = configured_settings()
    if config is None:
        return
    if head.repository.lower() != CHECKED_REPOSITORY or not _SHA_RE.fullmatch(head.head_sha):
        return
    if not _is_current_head(config, head):
        logger.info("docs_freshness: head superseded", pr_number=head.pr_number, head_sha=head.head_sha)
        return
    verdict = run_impact_check(config.tool_ref, head)
    if verdict.is_flagged:
        start_docs_agent(config, head, verdict)
    capture_verdict(config, head, "flagged" if verdict.is_flagged else "clear", len(verdict.impacted))


def record_unmergeable_verdict(head: PullRequestHead) -> None:
    config = configured_settings()
    if config is None:
        return
    capture_verdict(config, head, "unmergeable", 0)


def _is_current_head(config: DocsFreshnessSettings, head: PullRequestHead) -> bool:
    github = GitHubIntegration.first_for_team_repository(
        config.team_id, CHECKED_REPOSITORY, source="docs_freshness", priority=Priority.BATCH
    )
    if github is None:
        raise DocsFreshnessCheckError(
            f"No GitHub integration for team {config.team_id} can access {CHECKED_REPOSITORY}"
        )
    pull_request = github.get_pull_request(CHECKED_REPOSITORY, head.pr_number)
    if not pull_request.get("success"):
        raise DocsFreshnessCheckError(
            f"Reading pull request {head.pr_number} failed: {pull_request.get('error')}"[:300]
        )
    return pull_request.get("state") == "open" and pull_request.get("head_sha") == head.head_sha


def run_impact_check(tool_ref: str, head: PullRequestHead) -> ImpactVerdict:
    sandbox = get_sandbox_class().create(
        SandboxConfig(
            name=f"docs-freshness-{head.pr_number}",
            template=SandboxTemplate.SLIM_BASE,
            snapshot_id=None,
            memory_gb=4,
            cpu_cores=2,
            metadata={"purpose": "docs_freshness_impact_check"},
        )
    )
    try:
        return _read_verdict(sandbox, tool_ref, head)
    finally:
        try:
            sandbox.destroy()
        except Exception:
            logger.warning("docs_freshness: sandbox destroy failed", sandbox_id=sandbox.id, exc_info=True)


def _read_verdict(sandbox: SandboxBase, tool_ref: str, head: PullRequestHead) -> ImpactVerdict:
    result = sandbox.execute(_check_command(tool_ref, head), timeout_seconds=CHECK_TIMEOUT_SECONDS)
    if result.exit_code == MERGE_REF_BEHIND_HEAD_EXIT_CODE:
        raise MergeRefBehindHead(f"refs/pull/{head.pr_number}/merge does not hold head {head.head_sha} yet")
    if result.exit_code == MERGE_REF_MISSING_EXIT_CODE:
        raise MergeRefMissing(f"refs/pull/{head.pr_number}/merge does not exist")
    if result.exit_code not in (CLEAR_EXIT_CODE, FLAGGED_EXIT_CODE):
        raise DocsFreshnessCheckError(
            f"Impact check of pull request {head.pr_number} failed with exit code {result.exit_code}: "
            f"{result.stderr[-MAX_STDERR_CHARACTERS:]}"
        )
    impacted = tuple(json.loads(result.stdout))
    if result.exit_code == CLEAR_EXIT_CODE or not impacted:
        return ImpactVerdict(impacted=())
    prompt = sandbox.execute(f"cat {PROMPT_PATH}", timeout_seconds=PROMPT_TIMEOUT_SECONDS)
    if prompt.exit_code != 0:
        raise DocsFreshnessCheckError(f"Reading the docs agent prompt failed: {prompt.stderr[-MAX_STDERR_CHARACTERS:]}")
    return ImpactVerdict(impacted=impacted, prompt_template=prompt.stdout)


def _check_command(tool_ref: str, head: PullRequestHead) -> str:
    return (
        f"rm -rf {TOOL_DIRECTORY} && git init -q {TOOL_DIRECTORY} && "
        f"git -C {TOOL_DIRECTORY} fetch -q --depth=1 {TOOL_REPOSITORY_URL} {shlex.quote(tool_ref)} && "
        f"git -C {TOOL_DIRECTORY} checkout -q FETCH_HEAD || exit 10; "
        f"git ls-remote --exit-code {CHECKED_REPOSITORY_URL} refs/pull/{head.pr_number}/merge >/dev/null; "
        f'[ "$?" -ne {GIT_LS_REMOTE_NO_MATCH_EXIT_CODE} ] || exit {MERGE_REF_MISSING_EXIT_CODE}; '
        f"bash {TOOL_DIRECTORY}/docaudit/sandbox_check.sh refs/pull/{head.pr_number}/merge {head.head_sha} "
        f"2>{CHECK_STDERR_PATH}; check_status=$?; "
        f'[ "$check_status" -le {FLAGGED_EXIT_CODE} ] || tail -c 4000 {CHECK_STDERR_PATH} >&2; '
        f'exit "$check_status"'
    )


def docs_agent_description(head: PullRequestHead, verdict: ImpactVerdict) -> str:
    claims = [{name: entry[name] for name in ("page", "kind", "claim")} for entry in verdict.impacted]
    pages = sorted({claim["page"] for claim in claims})
    replacements = {
        "{event.properties.pr_url}": pull_request_url(head),
        "{event.properties.head_sha}": head.head_sha,
        "{event.properties.claims}": json.dumps(claims, indent=2),
        "{event.properties.pages}": json.dumps(pages),
    }
    description = verdict.prompt_template or ""
    for placeholder, value in replacements.items():
        description = description.replace(placeholder, value)
    return description


def checked_event_uuid(head: PullRequestHead) -> str:
    return str(uuid.uuid5(CHECKED_EVENT_UUID_NAMESPACE, f"{pull_request_url(head)}@{head.head_sha}"))


def start_docs_agent(config: DocsFreshnessSettings, head: PullRequestHead, verdict: ImpactVerdict) -> None:
    team = Team.objects.get(id=config.team_id)
    agent_started_marker_key = f"docs_freshness:agent_started:{checked_event_uuid(head)}"
    if not cache.add(agent_started_marker_key, True, timeout=AGENT_STARTED_MARKER_TIMEOUT_SECONDS):
        logger.info("docs_freshness: docs agent already started", pr_number=head.pr_number, head_sha=head.head_sha)
        return
    try:
        created = tasks_facade.create_and_run_task(
            team=team,
            title=f"docs: update for PostHog/posthog#{head.pr_number}",
            description=docs_agent_description(head, verdict),
            origin_product=tasks_facade.TaskOriginProduct.USER_CREATED,
            user_id=config.owner_user_id,
            repository=DOCS_REPOSITORY,
            create_pr=True,
            posthog_mcp_scopes=[],
        )
    except Exception:
        cache.delete(agent_started_marker_key)
        raise
    logger.info("docs_freshness: docs agent started", pr_number=head.pr_number, task_id=str(created.task_id))


def capture_verdict(
    config: DocsFreshnessSettings, head: PullRequestHead, verdict_name: str, impacted_claims: int
) -> None:
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=CAPTURE_DISTINCT_ID,
            event=CHECKED_EVENT,
            uuid=checked_event_uuid(head),
            properties={
                "$process_person_profile": False,
                "pr_url": pull_request_url(head),
                "repository": "PostHog/posthog",
                "pr_number": head.pr_number,
                "head_sha": head.head_sha,
                "verdict": verdict_name,
                "impacted_claims": impacted_claims,
                "tool_ref": config.tool_ref,
            },
        )
