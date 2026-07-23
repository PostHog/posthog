import json
from typing import Literal, get_args

import posthoganalytics

SANDBOX_EVENT_INGEST_FEATURE_FLAG = "tasks-cloud-runs-sandbox-event-ingest"
AGENT_PROXY_KEEP_STREAM_OPEN_FEATURE_FLAG = "tasks-agent-proxy-keep-stream-open"
MODAL_VM_SANDBOX_FEATURE_FLAG = "tasks-modal-vm-sandbox"
MODAL_NETWORK_ALLOWLIST_FEATURE_FLAG = "tasks-modal-network-allowlist"
AGENT_RUN_OTEL_TELEMETRY_FEATURE_FLAG = "tasks-agent-run-otel-telemetry"
# Run-state key the telemetry flag decision is stamped under at dispatch (temporal/client.py).
# Consumers read the stamp, so the decision stays stable for the run's whole lifetime.
AGENT_OTEL_TELEMETRY_STATE_KEY = "agent_otel_telemetry_enabled"


def vm_sandbox_allowed_origin_products(payload: object) -> set[str]:
    """Origin products allowed on the Modal VM runtime, parsed from the flag's payload."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            payload = None
    value = payload.get("origin_products") if isinstance(payload, dict) else payload
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return {item for item in value if isinstance(item, str)}
    return set()


def vm_sandbox_default_base_origin_products(payload: object) -> set[str]:
    """Origins allowed to run on the bare VM *base* image even without a custom image.

    This is the knob that makes the VM runtime the default for standard cloud runs: an
    origin listed here provisions on `SandboxTemplate.VM_BASE` instead of the gVisor
    default base, without requiring the user to pick a custom image. Read only from the
    explicit dict key — unlike `origin_products`, a bare-list payload keeps its legacy
    `origin_products` meaning and never opts an origin into the default base."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            payload = None
    value = payload.get("default_base_origin_products") if isinstance(payload, dict) else None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return {item for item in value if isinstance(item, str)}
    return set()


def get_vm_sandbox_flag_payload(*, distinct_id: str, organization_id: str) -> object:
    """Raw payload of the Modal VM-sandbox flag; resolves to None when the flag is off."""
    return posthoganalytics.get_feature_flag_payload(
        MODAL_VM_SANDBOX_FEATURE_FLAG,
        distinct_id=distinct_id,
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )


def vm_sandbox_allowed_origins(*, distinct_id: str, organization_id: str) -> set[str]:
    """Allowed origin products from the VM-sandbox flag; empty when off (payload only resolves on match)."""
    return vm_sandbox_allowed_origin_products(
        get_vm_sandbox_flag_payload(distinct_id=distinct_id, organization_id=organization_id)
    )


MAX_CUSTOM_IMAGES_PER_TEAM = 20
MAX_CUSTOM_IMAGES_PER_USER = 10

MODAL_DIRECTORY_RESUME_SNAPSHOTS_FEATURE_FLAG = "tasks-modal-directory-resume-snapshots"
STREAM_VIA_PROXY_FEATURE_FLAG = "tasks-stream-via-proxy"
OVERLAP_CLONE_BOOT_FEATURE_FLAG = "tasks-overlap-clone-boot"
# Kill switch: rtk command-output compression is on by default in cloud sandboxes;
# enabling this flag disables it fleet-wide — over any per-run override — without
# an image rebuild.
RTK_DISABLED_FEATURE_FLAG = "tasks-rtk-disabled"
# Gates whether long-running process_task runs continue-as-new to bound history/replay cost.
CONTINUE_AS_NEW_FEATURE_FLAG = "tasks-cloud-run-continue-as-new"

SnapshotKind = Literal["filesystem", "directory"]
SNAPSHOT_KIND_FILESYSTEM: SnapshotKind = "filesystem"
SNAPSHOT_KIND_DIRECTORY: SnapshotKind = "directory"
DEFAULT_SANDBOX_WORKING_DIR = "/tmp/workspace"
# Directory resume snapshots capture a directory and re-mount it into the next sandbox. The mount
# REPLACES the target directory in the running sandbox, so only the quiescent workspace dir is safe:
# mounting over a live system directory (the old "/tmp" default) rips scratch space and sockets out
# from under Modal's in-sandbox helpers and kills the sandbox on its first filesystem operation.
# A snapshot's content layout matches the path it was captured from, so snapshots created for a
# path outside this allowlist cannot be remapped — they must be invalidated on resume instead.
DEFAULT_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATH = DEFAULT_SANDBOX_WORKING_DIR
ALLOWED_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATHS: frozenset[str] = frozenset({DEFAULT_SANDBOX_WORKING_DIR})

ClaudePermissionMode = Literal["default", "acceptEdits", "plan", "bypassPermissions", "auto"]
CodexPermissionMode = Literal["plan", "auto", "read-only", "full-access"]
InitialPermissionMode = ClaudePermissionMode | CodexPermissionMode

# PostHog `exec` sub-tools that must be approved by the user before they run, passed to the
# agent-server as `--posthogExecPermissionRegex`. A matching sub-tool is relayed to the connected
# client in every non-background run regardless of permission mode (the client then decides:
# destructive sub-tools always prompt, persist/publish sub-tools prompt only on foreground streams,
# full-auto runs answer everything). Three alternatives: destructive verbs as `-`-bounded segments,
# the exact names of `annotations.destructive: true` tools the verb regex misses, and the exact
# persist/publish tool names from the apply-back product families. Must stay in sync with
# `POSTHOG_DESTRUCTIVE_SUBTOOL_RE`, `POSTHOG_DESTRUCTIVE_SUB_TOOLS`, and `PERSIST_PROMPT_SUB_TOOLS`
# in `products/posthog_ai/frontend/policy/toolPolicy.ts`.
POSTHOG_EXEC_DESTRUCTIVE_VERB_REGEX = r"(^|-)(partial-update|update|patch|delete|destroy)(-|$)"

# Enabled tools annotated `destructive: true` in `products/*/mcp/*.yaml` whose names carry no
# destructive verb segment (publish, ship, merge, archive, …). Kept complete against those
# annotations by `test_exec_permission_regex_covers_destructive_annotated_tools`.
POSTHOG_EXEC_DESTRUCTIVE_SUB_TOOLS: tuple[str, ...] = (
    # confirmed_action tools register only `<name>-execute` (and `-prepare`); the bare name is
    # never a runtime tool, so the destructive `-execute` variant is what must be gated.
    "change-requests-approve-execute",
    "change-requests-reject-execute",
    "error-tracking-bypass-rules-create",
    "error-tracking-issues-merge-create",
    "error-tracking-issues-split-create",
    "error-tracking-suppression-rules-create",
    "experiment-ship-variant",
    "external-data-schemas-resync",
    "external-data-sources-repair-cdc-create",
    "heatmaps-saved-regenerate",
    "inbox-reports-bulk-set-state",
    "inbox-reports-set-state",
    "llma-prompt-label-set",
    "organization-enforce-2fa",
    "organization-enforce-2fa-execute",
    "scout-scratchpad-forget",
    "signals-scout-scratchpad-forget",
    "skill-archive",
    "user-interview-topics-remove-interviewee",
    "visual-review-runs-finalize-create",
    "web-analytics-path-cleaning-suggestions-apply",
    "workflows-discard-draft",
    "workflows-publish",
    "workflows-restore-revision",
    "workflows-test-run",
)

# Non-destructive tools that persist new content (create/copy/add) or publish to end users
# (launch/stop), from the apply-back product families — the client prompts for these only on
# foreground streams.
POSTHOG_EXEC_PERSIST_SUB_TOOLS: tuple[str, ...] = (
    "dashboard-create",
    "dashboard-create-text-tile",
    "dashboard-tile-copy",
    "dashboard-widgets-batch-add",
    "create-feature-flag",
    "feature-flags-copy-flags-create",
    "scheduled-changes-create",
    "survey-create",
    "survey-launch",
    "survey-stop",
    "cdp-functions-create",
    "workflows-create",
    "workflows-create-email-template",
)

POSTHOG_EXEC_PERMISSION_REGEX = (
    POSTHOG_EXEC_DESTRUCTIVE_VERB_REGEX
    + "|^("
    + "|".join(POSTHOG_EXEC_DESTRUCTIVE_SUB_TOOLS + POSTHOG_EXEC_PERSIST_SUB_TOOLS)
    + ")$"
)

INITIAL_PERMISSION_MODE_CHOICES: list[str] = list(get_args(ClaudePermissionMode))
CODEX_INITIAL_PERMISSION_MODE_CHOICES: list[str] = list(get_args(CodexPermissionMode))
ALL_INITIAL_PERMISSION_MODE_CHOICES: list[str] = [
    arg for member in get_args(InitialPermissionMode) for arg in get_args(member)
]

DEFAULT_TRUSTED_DOMAINS = [
    # PostHog Services
    "posthog.com",
    "*.posthog.com",
    # Version Control
    "github.com",
    "www.github.com",
    "api.github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "codeload.github.com",
    "avatars.githubusercontent.com",
    "camo.githubusercontent.com",
    "gist.github.com",
    "gitlab.com",
    "www.gitlab.com",
    "registry.gitlab.com",
    "bitbucket.org",
    "www.bitbucket.org",
    "api.bitbucket.org",
    # Container Registries
    "registry-1.docker.io",
    "auth.docker.io",
    "index.docker.io",
    "hub.docker.com",
    "www.docker.com",
    "production.cloudflare.docker.com",
    "download.docker.com",
    "*.gcr.io",
    "ghcr.io",
    "mcr.microsoft.com",
    "*.data.mcr.microsoft.com",
    # Cloud Platforms
    "cloud.google.com",
    "accounts.google.com",
    "gcloud.google.com",
    "*.googleapis.com",
    "storage.googleapis.com",
    "compute.googleapis.com",
    "container.googleapis.com",
    "azure.com",
    "portal.azure.com",
    "microsoft.com",
    "www.microsoft.com",
    "*.microsoftonline.com",
    "packages.microsoft.com",
    "dotnet.microsoft.com",
    "dot.net",
    "visualstudio.com",
    "dev.azure.com",
    "oracle.com",
    "www.oracle.com",
    "java.com",
    "www.java.com",
    "java.net",
    "www.java.net",
    "download.oracle.com",
    "yum.oracle.com",
    # Package Managers - JavaScript/Node
    "registry.npmjs.org",
    "www.npmjs.com",
    "www.npmjs.org",
    "npmjs.com",
    "npmjs.org",
    "yarnpkg.com",
    "registry.yarnpkg.com",
    # Package Managers - Python
    "pypi.org",
    "www.pypi.org",
    "files.pythonhosted.org",
    "pythonhosted.org",
    "test.pypi.org",
    "pypi.python.org",
    "pypa.io",
    "www.pypa.io",
    # Package Managers - Ruby
    "rubygems.org",
    "www.rubygems.org",
    "api.rubygems.org",
    "index.rubygems.org",
    "ruby-lang.org",
    "www.ruby-lang.org",
    "rubyforge.org",
    "www.rubyforge.org",
    "rubyonrails.org",
    "www.rubyonrails.org",
    "rvm.io",
    "get.rvm.io",
    # Package Managers - Rust
    "crates.io",
    "www.crates.io",
    "static.crates.io",
    "rustup.rs",
    "static.rust-lang.org",
    "www.rust-lang.org",
    # Package Managers - Go
    "proxy.golang.org",
    "sum.golang.org",
    "index.golang.org",
    "golang.org",
    "www.golang.org",
    "goproxy.io",
    "pkg.go.dev",
    # Package Managers - JVM
    "maven.org",
    "repo.maven.org",
    "central.maven.org",
    "repo1.maven.org",
    "jcenter.bintray.com",
    "gradle.org",
    "www.gradle.org",
    "services.gradle.org",
    "spring.io",
    "repo.spring.io",
    # Package Managers - Other Languages
    "packagist.org",
    "www.packagist.org",
    "repo.packagist.org",
    "nuget.org",
    "www.nuget.org",
    "api.nuget.org",
    "pub.dev",
    "api.pub.dev",
    "hex.pm",
    "www.hex.pm",
    "cpan.org",
    "www.cpan.org",
    "metacpan.org",
    "www.metacpan.org",
    "api.metacpan.org",
    "cocoapods.org",
    "www.cocoapods.org",
    "cdn.cocoapods.org",
    "haskell.org",
    "www.haskell.org",
    "hackage.haskell.org",
    "swift.org",
    "www.swift.org",
    # Linux Distributions
    "archive.ubuntu.com",
    "security.ubuntu.com",
    "ubuntu.com",
    "www.ubuntu.com",
    "*.ubuntu.com",
    "ppa.launchpad.net",
    "launchpad.net",
    "www.launchpad.net",
    # Development Tools & Platforms
    "dl.k8s.io",
    "pkgs.k8s.io",
    "k8s.io",
    "www.k8s.io",
    "releases.hashicorp.com",
    "apt.releases.hashicorp.com",
    "rpm.releases.hashicorp.com",
    "archive.releases.hashicorp.com",
    "hashicorp.com",
    "www.hashicorp.com",
    "repo.anaconda.com",
    "conda.anaconda.org",
    "anaconda.org",
    "www.anaconda.com",
    "anaconda.com",
    "continuum.io",
    "apache.org",
    "www.apache.org",
    "archive.apache.org",
    "downloads.apache.org",
    "eclipse.org",
    "www.eclipse.org",
    "download.eclipse.org",
    "nodejs.org",
    "www.nodejs.org",
    # Cloud Services & Monitoring
    "statsig.com",
    "www.statsig.com",
    "api.statsig.com",
    "*.sentry.io",
    # Content Delivery & Mirrors
    "*.sourceforge.net",
    "packagecloud.io",
    "*.packagecloud.io",
    # Schema & Configuration
    "json-schema.org",
    "www.json-schema.org",
    "json.schemastore.org",
    "www.schemastore.org",
]

RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS: frozenset[str] = frozenset(
    {
        "POSTHOG_PERSONAL_API_KEY",
        "POSTHOG_WIZARD_API_KEY",
        "POSTHOG_API_URL",
        "POSTHOG_PROJECT_ID",
        "JWT_PUBLIC_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "LLM_GATEWAY_URL",
        "POSTHOG_RESUME_RUN_ID",
        "POSTHOG_AGENT_OTEL_LOGS_URL",
        "POSTHOG_AGENT_OTEL_LOGS_TOKEN",
        "POSTHOG_AGENT_OTEL_TRACES_URL",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
        "DISABLE_TELEMETRY",
        "DISABLE_ERROR_REPORTING",
    }
)

BLOCKED_SANDBOX_ENVIRONMENT_VARIABLE_PREFIXES: tuple[str, ...] = ("LD_", "DYLD_", "GIT_")
BLOCKED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS: frozenset[str] = frozenset(
    {
        "NODE_OPTIONS",
        "NODE_REPL_EXTERNAL_MODULE",
        "BASH_ENV",
        "PROMPT_COMMAND",
        "PYTHONSTARTUP",
        "PERL5OPT",
        "RUBYOPT",
    }
)

SANDBOX_AGENT_LAUNCH_UNSET_ENV_VARS: tuple[str, ...] = (
    "NODE_OPTIONS",
    "NODE_REPL_EXTERNAL_MODULE",
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "LD_AUDIT",
    "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH",
)


def is_blocked_sandbox_env_key(key: str) -> bool:
    if key in BLOCKED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS:
        return True
    return any(key.startswith(prefix) for prefix in BLOCKED_SANDBOX_ENVIRONMENT_VARIABLE_PREFIXES)


def filter_user_sandbox_env_vars(env_vars: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    safe: dict[str, str] = {}
    skipped: list[str] = []
    for key, value in env_vars.items():
        if key in RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS or is_blocked_sandbox_env_key(key):
            skipped.append(key)
            continue
        safe[key] = value
    return safe, skipped


SETUP_REPOSITORY_PROMPT = """
Your goal is to setup the repository in the current environment.

You are operating in a sandbox environment that is completely isolated and safe. You can execute any commands without risk - feel free to run builds, tests, install dependencies, or any other operations needed. You must install all dependencies necessary and setup the environment such that it is ready for executing code tasks.

CONTEXT:

CWD: {cwd}

REPOSITORY: {repository}

INSTRUCTIONS:

1. Install all dependencies necessary to run the repository
2. Run any setup scripts that are available
3. Verify the setup by running tests or build if available

DO NOT make any code changes to the repository. The final state of the disk of this sandbox is what will be used for subsequent tasks, so do not leave any cruft behind, and make sure the repository is in a ready to use state.

Rules:
- You should not ask the user for any input. This is run in a sandbox environment in a background process, so they will not be able to provide any input.
- The disk will be snapshooted immediately after you complete the task, and it will be reused for future tasks, so make sure everything you want is setup there.
- CRITICAL: You MUST NOT leave any uncommitted changes in the repository. The snapshot will be used to execute user tasks later, and we cannot modify their git history. Do not create any files that aren't already ignored by the repository's .gitignore, and do not add new entries to the .gitignore. If you accidentally create uncommitted files, you must delete them before completion. Check `git status` and ensure the working tree is clean at the end.
"""
