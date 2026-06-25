from products.review_hog.backend.reviewer.models.issues_review import IssuePriority

# SANDBOX
# Global cap on concurrent sandbox agents per process — tuned for the parallel (perspective × chunk) review
# to fan out wider; accepted tradeoff of more in-flight sandboxes for speed.
MAX_CONCURRENT_SANDBOXES = 10

# PUBLISH
# When False, the run produces the local review report but does not post anything to GitHub.
PUBLISH_REVIEW_ENABLED = False

# Priorities surfaced in the review body's per-chunk count and published as inline comments
# (CONSIDER is body-only context). Shared by the body renderer and the publisher so the two never drift.
PUBLISHED_PRIORITIES = {IssuePriority.MUST_FIX, IssuePriority.SHOULD_FIX}
