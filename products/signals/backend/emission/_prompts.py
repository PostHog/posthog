"""Shared actionability + summarization prompts for Tier-1 warehouse signal emitters.

Grouped by record shape (support ticket, issue-tracker issue, error-tracking issue) rather
than per source — the wording is identical across sources of the same shape. Each prompt keeps
the `{description}` placeholder the config validator requires; summarization prompts also keep
`{max_length}`.
"""

# ── Support tickets / conversations ──────────────────────────────────────────

TICKET_SUMMARIZATION_PROMPT = """Summarize this customer support ticket for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) that captures the core issue
2. A concise summary capturing the problem or request, the product area affected, and any relevant context like error messages or what the customer already tried

Strip email signatures, legal disclaimers, and system-generated footers — but keep quoted replies or conversation fragments if they add context about the issue.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

<ticket>
{description}
</ticket>
"""

TICKET_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given a customer support ticket, determine if it contains feedback that engineers could address with code changes (bug fixes, new features, performance improvements, etc.).

A ticket is ACTIONABLE if it describes:
- A bug, error, or unexpected behavior in the product
- A feature request or suggestion for improvement
- A usability issue or confusion about the product
- A performance problem
- A question about the product or product integrations
- An ask to help with the product
- and similar cases

A ticket is NOT_ACTIONABLE if it is:
- Spam, abuse, or profanity with no real feedback
- A request whose primary ask is a manual human action, not a code change (refunds, billing/payment changes, plan changes, invoice questions)
- A generic "thank you" or confirmation that an issue was resolved
- An auto-generated, bot, or out-of-office message
- An internal test message

When in doubt, classify as ACTIONABLE. It is worse to miss real feedback than to let some noise through.

<ticket>
{description}
</ticket>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

# ── Issue-tracker issues ─────────────────────────────────────────────────────

ISSUE_SUMMARIZATION_PROMPT = """Summarize this issue for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) that captures the core issue
2. A concise summary capturing the problem or request, the product area affected, and key context like error messages or what the user was doing when the issue occurred

Strip raw logs, full stack traces, and large code blocks — but keep specific error messages and high-level reproduction context if they clarify the issue.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

<issue>
{description}
</issue>
"""

ISSUE_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given a tracked issue, determine if it contains actionable product feedback.

An issue is ACTIONABLE if it describes:
- A bug, error, or unexpected behavior in the product
- A feature request or suggestion for improvement
- A usability issue or confusion about the product
- A performance problem or regression
- A question about how to use the product
- A gap or error in documentation that caused confusion
- and similar cases

An issue is NOT_ACTIONABLE if it is:
- A meta/tracking issue with no substantive feedback (release checklists, sprint trackers, epics that only link children)
- An internal housekeeping task (dependency bumps, CI config, infra maintenance)
- A duplicate that only says "same as X" with no new information

When in doubt, classify as ACTIONABLE. Issues are filed intentionally, so err on the side of capturing the signal.

<issue>
{description}
</issue>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

# ── Error / crash tracking ───────────────────────────────────────────────────

ERROR_SUMMARIZATION_PROMPT = """Summarize this application error for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) naming the error and where it occurs
2. A concise summary of the error class, message, and the affected product area or code path

Strip full stack traces and repeated frames — but keep the error class, the key message, and the most relevant frame if it clarifies the cause.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

<error>
{description}
</error>
"""

ERROR_ACTIONABILITY_PROMPT = """You are a product engineer triaging application errors. Given an error group, determine if it is actionable — a real defect an engineer could investigate or fix.

An error is ACTIONABLE if it describes:
- An unhandled exception, crash, or unexpected failure in the product
- A performance failure (timeout, out-of-memory, deadlock)
- A regression tied to a release or deploy
- and similar real defects

An error is NOT_ACTIONABLE if it is:
- Clearly caused by a client/network condition outside the product (e.g. user offline, request cancelled) with no product defect
- A known third-party/bot noise pattern with no product impact
- A test or synthetic error

When in doubt, classify as ACTIONABLE.

<error>
{description}
</error>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

# ── Security scanner findings ────────────────────────────────────────────────

SCANNER_SUMMARIZATION_PROMPT = """Summarize this security or code-quality finding for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) naming the finding and the affected component
2. A concise summary of the vulnerability or defect, its severity, and the affected code/asset

Strip long scanner boilerplate and repeated remediation text — keep the rule/CVE, severity, and the specific location or component.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

<finding>
{description}
</finding>
"""

SCANNER_ACTIONABILITY_PROMPT = """You are a security engineer triaging scanner findings. Given a finding, determine if it is actionable — a real vulnerability or code-quality defect an engineer could fix.

A finding is ACTIONABLE if it describes:
- A security vulnerability (injection, secret leak, vulnerable dependency, misconfiguration)
- A code-quality defect (bug pattern, reliability or maintainability issue)
- and similar real defects with a fix path

A finding is NOT_ACTIONABLE if it is:
- Explicitly triaged as a false positive or accepted risk
- Informational-only with no fix
- A duplicate of an already-tracked finding with no new information

When in doubt, classify as ACTIONABLE.

<finding>
{description}
</finding>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

# ── Product feedback / feature requests / surveys ────────────────────────────

FEEDBACK_SUMMARIZATION_PROMPT = """Summarize this product feedback for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) capturing the core request or sentiment
2. A concise summary of what the user wants or is frustrated by, and the product area affected

Strip pleasantries and boilerplate — keep the specific ask, use case, or pain point.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

<feedback>
{description}
</feedback>
"""

FEEDBACK_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given a piece of product feedback (a feature request, idea, or survey comment), determine if it contains actionable signal engineers or product could act on.

Feedback is ACTIONABLE if it describes:
- A feature request or concrete suggestion for improvement
- A bug, usability issue, or confusion about the product
- A specific unmet need or pain point with a use case
- and similar cases

Feedback is NOT_ACTIONABLE if it is:
- A generic "great product" / "thanks" with no substance
- Spam, abuse, or profanity with no real feedback
- An empty or single-word response with no context

When in doubt, classify as ACTIONABLE.

<feedback>
{description}
</feedback>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""

# ── App / product reviews ────────────────────────────────────────────────────

REVIEW_SUMMARIZATION_PROMPT = """Summarize this product review for semantic search.
Output exactly two parts separated by a newline:
1. A short title (under 100 characters) capturing the core sentiment or issue
2. A concise summary of what the reviewer liked or disliked, and the product area affected

Strip pleasantries — keep the specific praise, complaint, or requested change.
Keep the total output under {max_length} characters. Respond with only the title and summary, nothing else.

<review>
{description}
</review>
"""

REVIEW_ACTIONABILITY_PROMPT = """You are a product feedback analyst. Given an app or product review, determine if it contains actionable feedback engineers or product could act on.

A review is ACTIONABLE if it describes:
- A bug, crash, or broken behavior
- A missing feature or concrete improvement request
- A usability complaint or confusion tied to a specific area
- and similar cases

A review is NOT_ACTIONABLE if it is:
- A generic star rating with no substance ("great app", "love it", "bad")
- Spam, abuse, or profanity with no real feedback
- Off-topic content unrelated to the product

When in doubt, classify as ACTIONABLE.

<review>
{description}
</review>

Respond with exactly one word: ACTIONABLE or NOT_ACTIONABLE"""
