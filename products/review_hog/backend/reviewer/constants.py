from products.review_hog.backend.reviewer.models.issues_review import IssuePriority

# SANDBOX
# Per-child-workflow fan-out width: each Temporal fan-out (analyze / review / validate) bounds its
# concurrent sandbox-turn activities with a fresh `asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)`. The
# true global ceiling is the tasks-task-queue worker's own concurrency, where the sandboxes execute.
MAX_CONCURRENT_SANDBOXES = 10

# A fan-out stage (analyze / review / validate) degrades best-effort while at most this fraction of
# its units fail; above it the run fails loudly instead of finalizing a near-empty review as success
# (a total wipeout — e.g. the sandbox layer down — must not look like a clean PR).
FAN_OUT_FAILURE_FLOOR = 0.70

# PUBLISH
# When False, the run produces the local review report but does not post anything to GitHub.
PUBLISH_REVIEW_ENABLED = False

# Priorities surfaced in the review body's per-chunk count and published as inline comments
# (CONSIDER is body-only context). Shared by the body renderer and the publisher so the two never drift.
PUBLISHED_PRIORITIES = {IssuePriority.MUST_FIX, IssuePriority.SHOULD_FIX}
