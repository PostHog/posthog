"""Redaction applied to reviewer output before it leaves the product.

The reviewer runs an LLM over untrusted PR content, so its text can carry credentials or
auto-fetched markdown. Every surface that shows that text (GitHub reviews, the API) runs it
through these first.
"""

import os
import re


def llm_env_secrets() -> list[str]:
    """Non-empty LLM credential values in the worker env, gathered for output scrubbing.

    These reach the sandbox via ``_reviewer_environment``; a confused or compromised
    reviewer could echo them into stdout or the verdict. Redacting them server-side,
    independent of model behavior, is what keeps a leaked key out of the PR and the DB.
    POSTHOG_API_KEY is a public write token (spam-only blast radius) — scrubbed for tidiness.
    """
    return [
        value
        for key in ("AI_GATEWAY_API_KEY", "ANTHROPIC_API_KEY", "AI_GATEWAY_URL", "POSTHOG_API_KEY")
        if (value := os.environ.get(key))
    ]


# Inline markdown images and raw <img> tags in text GitHub renders — both are removed outright,
# URL included. Reference-style image forms are handled by the ``![`` demotion below.
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)|<img\b[^>]*>", re.IGNORECASE)


def neutralize_active_markdown(text: str) -> str:
    """Remove auto-fetched markdown constructs from reviewer-authored text before it reaches GitHub.

    The reviewer LLM reads untrusted PR content, so its output can be prompt-injected. Credential
    scrubbing is exact-string only — a token re-encoded (base64, split) into an image URL slips
    through, and GitHub fetching the image on render (through its camo proxy, no click needed) would
    exfiltrate it OUTSIDE the sandbox egress allowlist.

    Inline images and <img> tags are removed URL-and-all. Every OTHER markdown image form —
    reference ``![a][ref]``, collapsed, shortcut — starts with ``![``, so the trailing demotion to
    ``[`` turns anything left into a plain link, which GitHub never fetches without a click.
    Deliberately a syntax demotion rather than an enumeration of forms: an image form this function's
    author didn't think of still gets demoted. Plain links stay clickable, so legitimate references
    to code and PRs survive.
    """
    return _MARKDOWN_IMAGE_RE.sub("[image removed]", text).replace("![", "[")


def scrub_credentials(text: str, *secrets: str) -> str:
    """Redact credential material before it reaches ``ReviewRun``, the logs, or GitHub.

    Scrubs the passed GitHub token / basic-auth material plus any LLM credentials present
    in the worker env — deterministic, so it does not depend on what the reviewer emits.
    """
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    for secret in llm_env_secrets():
        text = text.replace(secret, "[redacted]")
    return text
