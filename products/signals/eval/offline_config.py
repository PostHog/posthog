from uuid import UUID

from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite

GROUPING_SUITE = OfflineEvalSuite(
    key="signals/grouping-e2e",
    tags=("team:self-driving", "component:signals/grouping"),
    project_id=2,
    scorer_kinds={
        "signal_safety_correct_classification": "boolean",
        "actionability_correct_classification": "boolean",
        "correct_match": "boolean",
        "correct_match_pre_specificity": "boolean",
        "query_diversity": "numeric",
        "candidate_diversity": "numeric",
        "report_safety_correct_classification": "boolean",
        "purity": "numeric",
        "is_pure": "boolean",
        "group_recall": "numeric",
        "ari": "numeric",
        "homogeneity": "numeric",
        "completeness": "numeric",
        "mean_purity": "numeric",
        "mean_group_recall": "numeric",
        "malicious_leaked_rate": "numeric",
    },
    scorer_versions={
        "signal_safety_correct_classification": UUID("01a14506-416d-7357-a737-75804a20a316"),
        "actionability_correct_classification": UUID("01a14506-87c8-7f79-b4f7-f0c685a6fa20"),
        "correct_match": UUID("01a14506-8e69-79f7-b568-5a03c2f98a47"),
        "correct_match_pre_specificity": UUID("01a14506-9622-78bb-93ab-4c049252329e"),
        "query_diversity": UUID("01a14506-9cc2-7977-a3e0-5cc661506e6d"),
        "candidate_diversity": UUID("01a14506-a39a-70c8-9f7e-c4b85e063ac1"),
        "report_safety_correct_classification": UUID("01a14506-aa45-7e64-91eb-baa67a43a37a"),
        "purity": UUID("01a14506-b1bd-7a5d-b1d9-2448036f5478"),
        "is_pure": UUID("01a14506-ba01-7d34-9f1c-925f870111ca"),
        "group_recall": UUID("01a14506-c495-74b6-b35d-c222b6ad116f"),
        "ari": UUID("01a14506-cc21-7c7f-b04c-8e55f21f1aad"),
        "homogeneity": UUID("01a14506-dba5-704e-953d-036417de6229"),
        "completeness": UUID("01a14506-e267-708a-9806-eb73f5353f4f"),
        "mean_purity": UUID("01a14506-eb0b-70e4-8b2c-ed5534529a93"),
        "mean_group_recall": UUID("01a14506-f383-7742-96eb-13ab08cdd697"),
        "malicious_leaked_rate": UUID("01a14506-fafc-75c0-8b15-73028c9cdeff"),
    },
)

SCOUT_SAFETY_SUITE = OfflineEvalSuite(
    key="signals/scout-safety",
    tags=("team:self-driving", "component:signals/scout-safety"),
    project_id=2,
    scorer_kinds={
        "scout_safety_correct_classification": "boolean",
        "false_positive_rate": "numeric",
        "payload_leak_rate": "numeric",
    },
    scorer_versions={
        "scout_safety_correct_classification": UUID("01a14507-0323-74ea-be20-8b9e858fa46c"),
        "false_positive_rate": UUID("01a14507-0a28-7118-89c5-96f38d37878b"),
        "payload_leak_rate": UUID("01a14507-101a-79a0-932f-40a8cee9cc72"),
    },
)
