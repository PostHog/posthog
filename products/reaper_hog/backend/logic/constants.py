import re

FLAG_UNCALLED_DAYS = 365
FLAG_DISABLED_DAYS = 90
FLAG_FULL_ROLLOUT_DAYS = 180

DIRECTORY_STALE_DAYS = 540
DIRECTORY_ORPHAN_DAYS = 180
DIRECTORY_HACKATHON_DAYS = 90
HACKATHON_SUBJECT = re.compile(r"hackathon|\bwip\b|\bspike\b|\bpoc\b|proof of concept", re.IGNORECASE)

MAX_REFERENCE_FILES = 40
MAX_DIRECTORY_LINES = 5000

ALL_SCOPE_ROOTS = ("products", "frontend/src/scenes", "posthog", "ee")

SUMMARY_NOTE_AUTHOR = "reaper-hog-scan"
