# SANDBOX
# Global cap on concurrent sandbox agents per process — tuned for the parallel (perspective × chunk) review
# to fan out wider; accepted tradeoff of more in-flight sandboxes for speed.
MAX_CONCURRENT_SANDBOXES = 10

# PUBLISH
# When False, the run produces the local review report but does not post anything to GitHub.
PUBLISH_REVIEW_ENABLED = False
