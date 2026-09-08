from pathlib import Path

from django.conf import settings

from products.tasks.backend.facade.sandbox import SandboxTemplate

WIZARD_TIMEOUT_SECONDS = 45 * 60
WIZARD_TIMEOUT_EXIT_CODE = 124
WIZARD_ERROR_DETAIL_LENGTH = 2000
WIZARD_ERROR_OUTPUT_PREFIX = "phw-error:"
MAX_HANDOFF_BODY_BYTES = 60_000
LOCAL_WIZARD_BUILD_TIMEOUT_SECONDS = 15 * 60
LOCAL_WIZARD_ARCHIVE_PATH = "/tmp/posthog-local-wizard.tar.gz"
LOCAL_WIZARD_INSTALL_PATH = "/tmp/posthog-local-wizard"
LOCAL_WIZARD_SOURCE_ENTRIES = (
    "README.md",
    "bin.ts",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "scripts",
    "src",
    "tsconfig.build.json",
    "tsconfig.json",
    "tsdown.config.ts",
    "types",
)

SANDBOX_EXECUTION_TIMEOUT_SECONDS = WIZARD_TIMEOUT_SECONDS + 120
SANDBOX_TTL_SECONDS = 75 * 60
SANDBOX_TEMPLATE_BASE = SandboxTemplate.SLIM_BASE
SANDBOX_MEMORY_GB = 4
SANDBOX_CPU_CORES = 2
SANDBOX_DISK_SIZE_GB = 16


def local_wizard_source_root() -> Path | None:
    value = getattr(settings, "LOCAL_WIZARD_ROOT", None)
    if not settings.DEBUG or not value:
        return None
    return Path(value).expanduser().resolve()
