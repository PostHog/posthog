from collections.abc import Mapping

from products.reaperhog.backend.logic.artefacts import EvidenceValue

# A harvest pull request is published to a repository that can be public, so scout evidence needs an
# allowlist before it leaves the product. A key that is absent from this set never reaches a pull
# request body. Counts read from event data (evaluations, unique users, pageviews) are deliberately
# absent, because they disclose the scanned project's traffic; the raw counts stay in the
# tenant-scoped artefact and in the private verification context. Internal row ids and the commit
# author address are absent for the same reason: a reviewer does not need them.
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
        "experiment_name",
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
        "author_left",
        "days_since_commit",
        # knip output
        "tool",
        "issue",
        "exports",
    }
)


def public_evidence(evidence: Mapping[str, EvidenceValue]) -> dict[str, EvidenceValue]:
    return {key: value for key, value in evidence.items() if key in PUBLIC_EVIDENCE_KEYS}
