import re
from collections.abc import Mapping

from products.reaperhog.backend.logic.artefacts import EvidenceValue

# A harvest pull request is published to a repository that can be public, so scout evidence needs an
# allowlist before it leaves the product. A key that is absent from this set never reaches a pull
# request body. Counts read from event data (evaluations, unique users, pageviews) are deliberately
# absent, because they disclose the scanned project's traffic; the raw counts stay in the
# tenant-scoped artefact and in the private verification context. Internal row ids, experiment names,
# the commit author address and the flag that says the author left the organization are absent for the
# same reason: they are project or personal data that the target repository does not hold.
PUBLIC_EVIDENCE_KEYS = frozenset(
    {
        # reference counts, read from the repository checkout
        "code_files",
        "test_files",
        "references",
        # flag configuration and staleness
        "status",
        "status_reason",
        "active",
        "deleted",
        "archived",
        "created_at",
        "updated_at",
        "last_called_at",
        "max_rollout_percentage",
        "has_enrollment_overrides",
        "fully_rolled_out_variant",
        "variants",
        # qualitative read of flag enrollment
        "enrollment_lookback_days",
        "sample_threshold_met",
        "enabled_seen",
        # experiment outcome and cleanup plan
        "conclusion",
        "end_date",
        "keep_variant",
        "remove_variants",
        "cleanup_confident",
        "cleanup_rationale",
        # scene routes, read from the source tree
        "routes",
        "lookback_days",
        # commit archaeology, read from the repository history
        "last_commit_sha",
        "last_commit_at",
        "last_commit_subject",
        "days_since_commit",
        # knip output
        "tool",
        "issue",
        "exports",
    }
)


def public_evidence(evidence: Mapping[str, EvidenceValue]) -> dict[str, EvidenceValue]:
    return {key: value for key, value in evidence.items() if key in PUBLIC_EVIDENCE_KEYS}


# Scout text carries values that people outside this product write: cleanup rationales built from
# variant keys, git commit subjects, knip export names. Those values reach the prompt of an agent that
# holds repository credentials, and they reach a published pull request body. Remove control characters
# and angle brackets, so a crafted value cannot close a delimited block and open one that imitates the
# prompt's own control channel, and cap the length so one value cannot fill the turn. No escaping stops
# plain-text influence, so each prompt also labels the block as data.
_UNSAFE_SCOUT_CHARS = re.compile(r"[\x00-\x1f\x7f<>]")
_MAX_SCOUT_CHARS = 500


def sanitize_text(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", _UNSAFE_SCOUT_CHARS.sub(" ", value)).strip()
    return cleaned[:_MAX_SCOUT_CHARS] + "…" if len(cleaned) > _MAX_SCOUT_CHARS else cleaned


def sanitize_scout_text(value: EvidenceValue) -> EvidenceValue:
    return sanitize_text(value) if isinstance(value, str) else value


# The verifier writes its argumentation, deletion plan and open questions from the same scout evidence,
# so its own prose reaches the harvest agent's prompt and the published pull request body as well. Keep
# the markdown readable — line breaks survive and the cap is wider — while removing the characters that
# let a quoted value close a delimited block or imitate the prompt's control channel.
_UNSAFE_PROSE_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f<>]")
_MAX_PROSE_CHARS = 4000


def sanitize_prose(value: str) -> str:
    cleaned = _UNSAFE_PROSE_CHARS.sub(" ", value).strip()
    return cleaned[:_MAX_PROSE_CHARS] + "…" if len(cleaned) > _MAX_PROSE_CHARS else cleaned
