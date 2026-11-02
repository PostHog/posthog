from datetime import timedelta

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.tasks.backend.facade.profiles import (
    DrivePolicy,
    GithubResolution,
    Read,
    TaskProfile,
    WarmPolicy,
    WarmQuota,
    task_profiles,
)
from products.tasks.backend.facade.run_config import WARMABLE_ORIGIN_PRODUCTS
from products.tasks.backend.logic.services.compute_quota import is_billable_compute
from products.tasks.backend.logic.services.sandbox import parse_requested_sandbox_template
from products.tasks.backend.logic.services.warm import SandboxWarmer
from products.tasks.backend.models import MCP_BUILT_IN_AGENT_KEY_BY_ORIGIN, Task, TaskClientProvenance
from products.tasks.backend.presentation.views.api import (
    WARM_SANDBOX_FLAGS_BY_ORIGIN_PRODUCT,
    WARM_SANDBOX_UNGATED_ORIGIN_PRODUCTS,
)
from products.tasks.backend.temporal.oauth import _oauth_application_for_task
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.start_agent_server import _include_personal_mcp_for_task
from products.tasks.backend.temporal.process_task.ai_gateway_token import resolve_sandbox_ai_product
from products.tasks.backend.temporal.process_task.utils import USER_AUTHORABLE_ORIGIN_PRODUCTS, get_pr_authorship_mode
from products.tasks.backend.visibility import (
    PRODUCT_PRIVATE_ORIGIN_PRODUCTS,
    TEAM_READABLE_ORIGIN_PRODUCTS,
    TEAM_VISIBLE_ORIGIN_PRODUCTS,
)

PROFILES = [(profile.key, profile) for profile in task_profiles()]
PROFILES_BY_REPOSITORY = [
    (f"{profile.key}_{'with' if has_repository else 'without'}_repository", profile, has_repository)
    for profile in task_profiles()
    for has_repository in (True, False)
]
MAX_RUN_DURATION_SECONDS = 3 * 60 * 60


def _task(profile: TaskProfile) -> Task:
    return Task(origin_product=profile.origin_product, internal=not profile.listed, team_id=1)


def _context(profile: TaskProfile) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="org-id",
        github_integration_id=None,
        repository=None,
        distinct_id="distinct",
        origin_product=profile.origin_product,
        state={"mode": "background"},
    )


def _master_warm_policy(origin_product: str) -> WarmPolicy | None:
    if origin_product not in SandboxWarmer.ORIGIN_PRODUCT_QUOTA:
        return None
    caps = SandboxWarmer.ORIGIN_PRODUCT_CAPS.get(origin_product, SandboxWarmer._DEFAULT_CAPS)
    checker = SandboxWarmer.ORIGIN_PRODUCT_QUOTA[origin_product]
    return WarmPolicy(
        quota=WarmQuota.NONE if checker is None else WarmQuota.AI_CREDITS,
        per_user_cap=caps.per_user,
        per_org_cap=caps.per_org,
        feature_flag=None
        if origin_product in WARM_SANDBOX_UNGATED_ORIGIN_PRODUCTS
        else WARM_SANDBOX_FLAGS_BY_ORIGIN_PRODUCT.get(origin_product),
    )


class TestTaskProfilesMatchMaster(SimpleTestCase):
    @parameterized.expand(PROFILES)
    def test_read_without_channel_matches_master(self, _key: str, profile: TaskProfile) -> None:
        team_readable = profile.origin_product in TEAM_READABLE_ORIGIN_PRODUCTS
        self.assertEqual(profile.read_without_channel, Read.TEAM if team_readable else Read.CREATOR)

    @parameterized.expand(PROFILES)
    def test_drive_matches_master(self, _key: str, profile: TaskProfile) -> None:
        team_visible = profile.origin_product in TEAM_VISIBLE_ORIGIN_PRODUCTS
        self.assertEqual(profile.drive, DrivePolicy.AUDIENCE if team_visible else DrivePolicy.OWNER)

    @parameterized.expand(PROFILES)
    def test_api_visible_matches_master(self, _key: str, profile: TaskProfile) -> None:
        self.assertEqual(profile.api_visible, profile.origin_product not in PRODUCT_PRIVATE_ORIGIN_PRODUCTS)

    @parameterized.expand(PROFILES)
    @override_settings(TEST=False, TASKS_INACTIVITY_TIMEOUT_SECONDS=0)
    def test_idle_minutes_matches_master(self, _key: str, profile: TaskProfile) -> None:
        self.assertEqual(_context(profile).inactivity_timeout(), timedelta(minutes=profile.idle_minutes))

    @parameterized.expand(PROFILES)
    @override_settings(TASKS_MAX_RUN_DURATION_SECONDS=MAX_RUN_DURATION_SECONDS)
    def test_max_wake_minutes_matches_master(self, _key: str, profile: TaskProfile) -> None:
        expected = None if profile.max_wake_minutes is None else timedelta(minutes=profile.max_wake_minutes)
        self.assertEqual(_context(profile).max_run_duration(), expected)

    @parameterized.expand(PROFILES)
    def test_warm_matches_master(self, _key: str, profile: TaskProfile) -> None:
        self.assertEqual(profile.warm, _master_warm_policy(profile.origin_product))
        self.assertEqual(profile.warm is not None, profile.origin_product in WARMABLE_ORIGIN_PRODUCTS)

    @parameterized.expand(PROFILES)
    def test_billing_product_matches_master(self, _key: str, profile: TaskProfile) -> None:
        master = resolve_sandbox_ai_product(profile.origin_product, None, internal=not profile.listed)
        self.assertEqual(profile.billing_product, master)

    @parameterized.expand(PROFILES)
    def test_bills_compute_matches_master(self, _key: str, profile: TaskProfile) -> None:
        master = is_billable_compute(
            origin_product=profile.origin_product, client_provenance=TaskClientProvenance.POSTHOG_DESKTOP
        )
        self.assertEqual(profile.bills_compute, master)

    @parameterized.expand(PROFILES)
    def test_oauth_app_matches_master(self, _key: str, profile: TaskProfile) -> None:
        self.assertEqual(profile.oauth_app, _oauth_application_for_task(_task(profile), None))

    @parameterized.expand(PROFILES)
    def test_mcp_agent_matches_master(self, _key: str, profile: TaskProfile) -> None:
        self.assertEqual(profile.mcp_agent, MCP_BUILT_IN_AGENT_KEY_BY_ORIGIN.get(profile.origin_product))

    @parameterized.expand(PROFILES)
    def test_personal_mcp_matches_master(self, _key: str, profile: TaskProfile) -> None:
        self.assertEqual(profile.personal_mcp, _include_personal_mcp_for_task(_task(profile)))

    @parameterized.expand(PROFILES)
    def test_inherit_user_defaults_matches_master(self, _key: str, profile: TaskProfile) -> None:
        with patch(
            "products.tasks.backend.logic.services.ai_run_defaults.apply_ai_run_defaults", return_value=None
        ) as apply_defaults:
            _task(profile)._apply_ai_run_defaults({}, acting_user_id=1)

        self.assertEqual(profile.inherit_user_defaults, apply_defaults.called)

    @parameterized.expand(PROFILES_BY_REPOSITORY)
    def test_github_resolution_matches_master(self, _name: str, profile: TaskProfile, has_repository: bool) -> None:
        attaches_github = {
            GithubResolution.ALWAYS: True,
            GithubResolution.WITH_REPOSITORY: has_repository,
            GithubResolution.NEVER: False,
        }[profile.github_resolution]
        master = Task._github_resolution_allowed(profile.origin_product, has_repository=has_repository)
        self.assertEqual(attaches_github, master)

    @parameterized.expand(PROFILES)
    def test_user_authorable_prs_matches_master(self, _key: str, profile: TaskProfile) -> None:
        self.assertEqual(profile.user_authorable_prs, profile.origin_product in USER_AUTHORABLE_ORIGIN_PRODUCTS)

    @parameterized.expand(PROFILES)
    def test_default_pr_authorship_matches_master(self, _key: str, profile: TaskProfile) -> None:
        self.assertEqual(profile.default_pr_authorship, get_pr_authorship_mode(_task(profile), None))

    @parameterized.expand(PROFILES)
    def test_default_runtime_matches_master(self, _key: str, profile: TaskProfile) -> None:
        self.assertEqual(profile.runtimes[0], Task.Runtime.ACP)

    @parameterized.expand(PROFILES)
    def test_default_sandbox_template_matches_master(self, _key: str, profile: TaskProfile) -> None:
        self.assertEqual(profile.sandbox_templates[0], parse_requested_sandbox_template(None).value)
