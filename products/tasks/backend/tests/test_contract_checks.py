from dataclasses import replace

from django.test import SimpleTestCase

import structlog.testing
from parameterized import parameterized
from prometheus_client import REGISTRY

from products.tasks.backend.facade.profiles import (
    ContractCheck,
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
