from collections.abc import Sequence
from uuid import UUID

from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, OfflineScorer] = {
    "assessment_only_no_edit_claim": OfflineScorer(
        kind="boolean", version=UUID("01a15a28-f08d-773f-ab1a-88323b444706")
    ),
    "attempted_tool": OfflineScorer(kind="boolean", version=UUID("01a15a29-15e7-7a4d-bc3e-cbc2a6d7fde5")),
    "avoided_tool": OfflineScorer(kind="boolean", version=UUID("01a15a29-229f-7a8c-96ad-e2e4070f634e")),
    "called_expected_tool": OfflineScorer(kind="boolean", version=UUID("01a15a29-0a13-76c8-9fa1-620c98110555")),
    "cleanup_skill_triggered": OfflineScorer(kind="boolean", version=UUID("01a15a28-8366-71a4-9790-39b96dec786e")),
    "code_edit_direction": OfflineScorer(kind="boolean", version=UUID("01a15a28-a1c4-71a9-8d49-14fecb1fcf6e")),
    "created_flag_configuration": OfflineScorer(kind="boolean", version=UUID("01a15a29-7bfc-7ed2-9b70-3efd6f845ef2")),
    "created_flag_with_tags": OfflineScorer(kind="boolean", version=UUID("01a15a29-2de7-7a7d-b0a2-b7cf40ca00df")),
    "dependents_check_direction": OfflineScorer(kind="boolean", version=UUID("01a15a28-b815-7ce3-b591-524d66fd33b4")),
    "edited_a_file": OfflineScorer(kind="boolean", version=UUID("01a15a29-e150-7307-aaa9-e9228706f89e")),
    "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a15a28-fcc8-71df-b886-752d5b82a419")),
    "explained_key_reuse": OfflineScorer(kind="boolean", version=UUID("01a15a29-c36a-7bef-95ad-b5151cf2bfb9")),
    "explained_tag_requirement": OfflineScorer(kind="boolean", version=UUID("01a15a29-70ca-7bb0-86bf-6430216b3ac7")),
    "final_message_names": OfflineScorer(kind="boolean", version=UUID("01a15a29-38b0-71c0-bfd9-419cd39d6847")),
    "flag_lookup_direction": OfflineScorer(kind="boolean", version=UUID("01a15a28-ae91-7185-9bce-80cd868d7c50")),
    "flag_state_unchanged": OfflineScorer(kind="boolean", version=UUID("01a15a28-9755-7c4a-8139-56ed6d942103")),
    "generic_update_omits_fields": OfflineScorer(kind="boolean", version=UUID("01a15a29-9766-741f-8775-fff77c2c81ff")),
    "generic_update_sets_fields": OfflineScorer(kind="boolean", version=UUID("01a15a29-a338-7a79-8b29-acd7a2aec492")),
    "instrument_flags_skill_triggered": OfflineScorer(
        kind="boolean", version=UUID("01a15a29-cf2e-74a8-a6af-a66281cd8637")
    ),
    "no_flag_mutation": OfflineScorer(kind="boolean", version=UUID("01a15a28-8cb1-7485-8766-e631517451fd")),
    "preserved_unrelated_config": OfflineScorer(kind="boolean", version=UUID("01a15a29-af51-7ae8-94e3-115000b1e2bb")),
    "recency_refusal_without_override": OfflineScorer(
        kind="boolean", version=UUID("01a15a28-d41d-7793-818b-ca478ebf5ba3")
    ),
    "refused_without_blaming": OfflineScorer(kind="boolean", version=UUID("01a15a29-583d-7c75-80d5-cff77fd3047b")),
    "resolved_flag_by_key": OfflineScorer(kind="boolean", version=UUID("01a15a29-8600-7983-b104-6c30aa8ab6bd")),
    "schedule_check_direction": OfflineScorer(kind="boolean", version=UUID("01a15a28-c70e-7c31-a7ff-2ad25d23d410")),
    "stale_is_not_safe_to_remove": OfflineScorer(kind="boolean", version=UUID("01a15a29-47b0-7e3d-b7f4-d1e6775c9ff2")),
    "tour_unknown_waits": OfflineScorer(kind="boolean", version=UUID("01a15a28-e252-76a5-8945-0321df22e8fa")),
    "updated_rollout_to": OfflineScorer(kind="boolean", version=UUID("01a15a29-b8a7-7873-aada-8d3d0f396eb4")),
}


def offline_suite(key: str, *, metrics: Sequence[str], suite_kind: SuiteKind = SuiteKind.SANDBOXED) -> OfflineEvalSuite:
    enrolled_metrics = ("exit_code_zero", *metrics) if suite_kind == SuiteKind.SANDBOXED else metrics
    return OfflineEvalSuite.from_scorers(
        key=key,
        project_id=2,
        scorers={metric: _SCORERS[metric] for metric in enrolled_metrics},
        tags=("team:feature-flags", "component:feature-flags"),
    )
