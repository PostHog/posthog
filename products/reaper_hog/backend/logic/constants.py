import re

from products.tasks.backend.facade.run_config import ReasoningEffort, RuntimeAdapter

FLAG_UNCALLED_DAYS = 365
FLAG_DISABLED_DAYS = 90
FLAG_FULL_ROLLOUT_DAYS = 180

SCENE_LOOKBACK_DAYS = 90

DIRECTORY_STALE_DAYS = 540
DIRECTORY_ORPHAN_DAYS = 180
DIRECTORY_HACKATHON_DAYS = 90
HACKATHON_SUBJECT = re.compile(r"hackathon|\bwip\b|\bspike\b|\bpoc\b|proof of concept", re.IGNORECASE)

MAX_REFERENCE_FILES = 40
MAX_DIRECTORY_LINES = 5000

ALL_SCOPE_ROOTS = ("products", "frontend/src/scenes", "posthog", "ee")

SUMMARY_NOTE_AUTHOR = "reaper-hog-scan"
VERIFICATION_NOTE_AUTHOR = "reaper-hog-verify"

VERIFICATION_SKILL_NAME = "reaper-hog-verification-criteria"
VERIFICATION_RUNTIME_ADAPTER: RuntimeAdapter | None = RuntimeAdapter.CLAUDE
VERIFICATION_MODEL: str | None = "claude-opus-5"
VERIFICATION_REASONING_EFFORT: ReasoningEffort | None = ReasoningEffort.XHIGH
VERIFICATION_INITIAL_PERMISSION_MODE: str | None = None
MAX_VERIFICATIONS_PER_RUN = 20

MAX_OPEN_REAPER_PRS = 3
MAX_FILES_PER_PR = 15
HARVEST_LABEL = "reaper-hog"
HARVEST_NOTE_AUTHOR = "reaper-hog-harvest"

REAPER_MCP_SCOPES: list[str] = ["llm_skill:read", "user:read"]
