from dataclasses import replace

from unittest.mock import patch

from django.test import SimpleTestCase

import structlog.testing
from parameterized import parameterized
from prometheus_client import REGISTRY

from products.tasks.backend.contract_checks import drive_allowed
from products.tasks.backend.facade.profiles import (
    ContractCheck,
    DrivePolicy,
    GithubAccess,
    TaskProfile,
    TaskRunOptions,
    TaskRunOptionsError,
    get_task_profile,
)
from products.tasks.backend.run_options import RunOptionsCaller, validate_run_options

SERVER = RunOptionsCaller.SERVER
PUBLIC = RunOptionsCaller.PUBLIC

LOG_PROFILE = replace(
    get_task_profile("business_knowledge"),
    key="test.run_option_checks",
    public_options=frozenset({"model", "idle_minutes"}),
    runtimes=("acp", "pi"),
    sandbox_templates=("default_base", "autoresearch_base"),
    mcp_scopes="read_only",
    github_access=GithubAccess.READ,
    idle_minutes=30,
)
ENFORCE_PROFILE = replace(LOG_PROFILE, enforced_checks=frozenset(ContractCheck))
WIDE_OPTIONS = TaskRunOptions(
    runtime="other",
    sandbox_template="vm_base",
    mcp_scopes="full",
    github_access=GithubAccess.WRITE,
    idle_minutes=31,
)

CASES = [
    ("runtime_in_list", TaskRunOptions(runtime="pi"), SERVER, ()),
    ("runtime_outside_list", TaskRunOptions(runtime="other"), SERVER, (ContractCheck.RUNTIMES,)),
    ("template_in_list", TaskRunOptions(sandbox_template="autoresearch_base"), SERVER, ()),
    ("template_outside_list", TaskRunOptions(sandbox_template="vm_base"), SERVER, (ContractCheck.SANDBOX_TEMPLATES,)),
    ("scopes_narrower", TaskRunOptions(mcp_scopes=["project:read"]), SERVER, ()),
    ("scopes_equal", TaskRunOptions(mcp_scopes="read_only"), SERVER, ()),
    ("scopes_wider", TaskRunOptions(mcp_scopes="full"), SERVER, (ContractCheck.MCP_SCOPES,)),
    (
        "scopes_partly_wider",
        TaskRunOptions(mcp_scopes=["project:read", "dashboard:write"]),
        SERVER,
        (ContractCheck.MCP_SCOPES,),
    ),
    ("github_none", TaskRunOptions(github_access=GithubAccess.NONE), SERVER, ()),
    ("github_equal", TaskRunOptions(github_access=GithubAccess.READ), SERVER, ()),
    ("github_wider", TaskRunOptions(github_access=GithubAccess.WRITE), SERVER, (ContractCheck.GITHUB_ACCESS,)),
    ("idle_lower", TaskRunOptions(idle_minutes=5), SERVER, ()),
    ("idle_equal", TaskRunOptions(idle_minutes=30), SERVER, ()),
    ("idle_higher", TaskRunOptions(idle_minutes=31), SERVER, (ContractCheck.IDLE_MINUTES,)),
    (
        "some_options_widen",
        TaskRunOptions(runtime="pi", sandbox_template="vm_base", idle_minutes=31, mcp_scopes=["project:read"]),
        SERVER,
        (ContractCheck.SANDBOX_TEMPLATES, ContractCheck.IDLE_MINUTES),
    ),
    (
        "every_option_widens",
        WIDE_OPTIONS,
        SERVER,
        tuple(set(ContractCheck) - {ContractCheck.PUBLIC_OPTIONS, ContractCheck.DRIVE}),
    ),
    ("public_options_only", TaskRunOptions(model="m", idle_minutes=5), PUBLIC, ()),
    ("public_option_outside_list", TaskRunOptions(runtime="acp"), PUBLIC, (ContractCheck.PUBLIC_OPTIONS,)),
    (
        "public_options_partly_outside_list",
        TaskRunOptions(model="m", idle_minutes=5, fast_mode=True),
        PUBLIC,
        (ContractCheck.PUBLIC_OPTIONS,),
    ),
    ("public_without_options", TaskRunOptions(), PUBLIC, ()),
    ("server_sets_option_outside_public_list", TaskRunOptions(runtime="acp"), SERVER, ()),
]


def _violation_counts(profile: TaskProfile) -> dict[ContractCheck, float]:
    return {
        check: REGISTRY.get_sample_value(
            "posthog_tasks_contract_violation_total", {"check": check.value, "profile": profile.key}
        )
        or 0
        for check in ContractCheck
    }


class TestValidateRunOptions(SimpleTestCase):
    @parameterized.expand(CASES)
    def test_log_mode_counts_each_violation_and_refuses_nothing(
        self, _name: str, options: TaskRunOptions, caller: RunOptionsCaller, violated: tuple[ContractCheck, ...]
    ) -> None:
        before = _violation_counts(LOG_PROFILE)

        with structlog.testing.capture_logs() as logs:
            validate_run_options(LOG_PROFILE, options, caller=caller)

        after = _violation_counts(LOG_PROFILE)
        self.assertEqual({check for check in ContractCheck if after[check] - before[check] == 1}, set(violated))
        self.assertEqual({check for check in ContractCheck if after[check] - before[check] > 1}, set())
        self.assertEqual(
            {(log["event"], log["check"]) for log in logs},
            {("task_contract_violation_would_refuse", check.value) for check in violated},
        )

    @parameterized.expand(CASES)
    def test_enforce_mode_refuses_the_options_that_widen_the_profile(
        self, _name: str, options: TaskRunOptions, caller: RunOptionsCaller, violated: tuple[ContractCheck, ...]
    ) -> None:
        with structlog.testing.capture_logs() as logs:
            if violated:
                with self.assertRaises(TaskRunOptionsError):
                    validate_run_options(ENFORCE_PROFILE, options, caller=caller)
            else:
                validate_run_options(ENFORCE_PROFILE, options, caller=caller)

        self.assertEqual({log["check"] for log in logs}, {check.value for check in violated})
        self.assertEqual({log["event"] for log in logs}, {"task_contract_violation_refused"} if violated else set())

    @parameterized.expand(
        [
            ("enforced_check_violated", {ContractCheck.RUNTIMES}, TaskRunOptions(runtime="other"), True),
            (
                "enforced_check_violated_beside_another",
                {ContractCheck.RUNTIMES},
                TaskRunOptions(runtime="other", sandbox_template="vm_base"),
                True,
            ),
            ("other_check_violated", {ContractCheck.RUNTIMES}, TaskRunOptions(sandbox_template="vm_base"), False),
            ("enforced_check_kept", {ContractCheck.RUNTIMES}, TaskRunOptions(runtime="pi", idle_minutes=31), False),
        ]
    )
    def test_enforcement_is_per_check(
        self, _name: str, enforced: set[ContractCheck], options: TaskRunOptions, refused: bool
    ) -> None:
        profile = replace(LOG_PROFILE, enforced_checks=frozenset(enforced))

        if refused:
            with self.assertRaisesRegex(TaskRunOptionsError, "runtime other") as context:
                validate_run_options(profile, options)
            self.assertNotIn("sandbox_template", str(context.exception))
        else:
            validate_run_options(profile, options)

    @parameterized.expand([("without_profile", None, WIDE_OPTIONS), ("without_options", ENFORCE_PROFILE, None)])
    def test_nothing_to_check_changes_nothing(
        self, _name: str, profile: TaskProfile | None, options: TaskRunOptions | None
    ) -> None:
        before = _violation_counts(ENFORCE_PROFILE)

        validate_run_options(profile, options, caller=PUBLIC)

        self.assertEqual(_violation_counts(ENFORCE_PROFILE), before)


DRIVE_CASES = [
    ("audience_owner", DrivePolicy.AUDIENCE, 1, 1, False),
    ("audience_other_user", DrivePolicy.AUDIENCE, 1, 2, False),
    ("audience_task_without_owner", DrivePolicy.AUDIENCE, None, 2, False),
    ("owner_drives_own_task", DrivePolicy.OWNER, 1, 1, False),
    ("owner_policy_other_user", DrivePolicy.OWNER, 1, 2, True),
    ("owner_policy_task_without_owner", DrivePolicy.OWNER, None, 2, True),
    ("owner_policy_without_user", DrivePolicy.OWNER, 1, None, True),
    ("none_policy_owner", DrivePolicy.NONE, 1, 1, True),
    ("none_policy_other_user", DrivePolicy.NONE, 1, 2, True),
]


def _drive_profile(drive: DrivePolicy, enforced: frozenset[ContractCheck] = frozenset()) -> TaskProfile:
    return replace(LOG_PROFILE, key="test.drive_checks", drive=drive, enforced_checks=enforced)


class TestDriveAllowed(SimpleTestCase):
    def _allowed(self, profile: TaskProfile, *, created_by_id: int | None, user_id: int | None) -> bool:
        with patch.dict("products.tasks.backend.facade.profiles._profiles", {profile.key: profile}):
            return drive_allowed(profile.key, created_by_id=created_by_id, user_id=user_id)

    @parameterized.expand(DRIVE_CASES)
    def test_log_mode_allows_every_caller_and_counts_those_it_would_refuse(
        self, _name: str, drive: DrivePolicy, created_by_id: int | None, user_id: int | None, violates: bool
    ) -> None:
        profile = _drive_profile(drive)
        before = _violation_counts(profile)

        allowed = self._allowed(profile, created_by_id=created_by_id, user_id=user_id)

        self.assertTrue(allowed)
        self.assertEqual(_violation_counts(profile)[ContractCheck.DRIVE] - before[ContractCheck.DRIVE], int(violates))

    @parameterized.expand(DRIVE_CASES)
    def test_enforce_mode_refuses_the_callers_the_policy_does_not_allow(
        self, _name: str, drive: DrivePolicy, created_by_id: int | None, user_id: int | None, violates: bool
    ) -> None:
        profile = _drive_profile(drive, frozenset({ContractCheck.DRIVE}))

        self.assertEqual(self._allowed(profile, created_by_id=created_by_id, user_id=user_id), not violates)

    @parameterized.expand([(name, *case) for name, *case in DRIVE_CASES if case[-1]])
    def test_enforcing_another_check_leaves_drive_in_log_mode(
        self, _name: str, drive: DrivePolicy, created_by_id: int | None, user_id: int | None, _violates: bool
    ) -> None:
        profile = _drive_profile(drive, frozenset({ContractCheck.RUNTIMES}))

        self.assertTrue(self._allowed(profile, created_by_id=created_by_id, user_id=user_id))

    @parameterized.expand([("no_key", None), ("empty_key", "")])
    def test_a_task_without_a_stored_profile_is_always_drivable(self, _name: str, profile_key: str | None) -> None:
        before = _violation_counts(_drive_profile(DrivePolicy.NONE))

        self.assertTrue(drive_allowed(profile_key, created_by_id=1, user_id=2))

        self.assertEqual(_violation_counts(_drive_profile(DrivePolicy.NONE)), before)

    def test_a_stored_key_that_is_not_registered_is_counted_by_its_key_and_still_drivable(self) -> None:
        sample = {"check": ContractCheck.DRIVE.value, "profile": "test.removed_profile"}
        before = REGISTRY.get_sample_value("posthog_tasks_contract_violation_total", sample) or 0

        with structlog.testing.capture_logs() as logs:
            allowed = drive_allowed("test.removed_profile", created_by_id=1, user_id=2)

        self.assertTrue(allowed)
        self.assertEqual((REGISTRY.get_sample_value("posthog_tasks_contract_violation_total", sample) or 0) - before, 1)
        self.assertEqual(
            [(log["event"], log["profile"]) for log in logs],
            [("task_contract_violation_unregistered_profile", "test.removed_profile")],
        )
