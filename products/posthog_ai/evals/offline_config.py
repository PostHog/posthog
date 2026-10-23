from collections.abc import Sequence
from uuid import UUID

from products.posthog_ai.eval_harness.harness.requirements import SuiteKind
from products.posthog_ai.eval_harness.offline_results import OfflineEvalSuite, OfflineScorer

_SCORERS: dict[str, dict[str, OfflineScorer]] = {
    "ci": {
        "called_target_tool": OfflineScorer(kind="boolean", version=UUID("01a1557d-d3f2-7807-88ff-12d4c4b2679c")),
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1557d-ca2a-75c8-b3a4-5b9a0a405a64")),
        "surfaced_generated_app_url": OfflineScorer(
            kind="boolean", version=UUID("01a1557d-dda3-782a-a2cb-dac316f6e7d6")
        ),
    },
    "cli_mcp": {
        "called_target_tool": OfflineScorer(kind="boolean", version=UUID("01a1557e-090d-700e-8bc7-584c54a089fc")),
        "did_not_cite_raw_sql_after_typed_query": OfflineScorer(
            kind="boolean", version=UUID("01a1557e-1c0f-7302-96f5-ccdb2eed2b27")
        ),
        "did_not_render_ui": OfflineScorer(kind="boolean", version=UUID("01a1557e-1330-7ce0-a05a-914503a66cb0")),
        "drilled_into_schema": OfflineScorer(kind="boolean", version=UUID("01a1557e-fd96-783d-8de2-dc4ddb5d6468")),
        "excluded_skill_not_loaded": OfflineScorer(
            kind="boolean", version=UUID("01a1557e-aca4-7826-8388-c66db0633772")
        ),
        "exec_before_render": OfflineScorer(kind="boolean", version=UUID("01a1557d-fb44-769a-b5cf-6d96a971182d")),
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1557d-e737-7f9a-bb69-3dae3e58df7c")),
        "expected_reference_pulled": OfflineScorer(
            kind="boolean", version=UUID("01a1557e-d5f9-7e74-8369-2e4627c02a4a")
        ),
        "expected_skill_discovered": OfflineScorer(
            kind="boolean", version=UUID("01a1557e-354f-726f-8e3e-c04ad776e8a7")
        ),
        "expected_skill_loaded": OfflineScorer(kind="boolean", version=UUID("01a1557e-a3f3-72c2-899f-3d5d9c903b39")),
        "info_before_call": OfflineScorer(kind="boolean", version=UUID("01a1557f-1350-7eb4-8821-1b38bb2d8325")),
        "no_bundled_skill_bypass": OfflineScorer(kind="boolean", version=UUID("01a1557e-c286-7545-a3ba-14a8e354cafe")),
        "no_exec_skill_bypass": OfflineScorer(kind="boolean", version=UUID("01a1557e-cb02-7a20-a775-8dd932e4d07c")),
        "preferred_search_over_tools": OfflineScorer(
            kind="boolean", version=UUID("01a1557f-0679-7a2e-9cc6-a0559e513dcd")
        ),
        "ran_python_post_processing": OfflineScorer(
            kind="boolean", version=UUID("01a1557f-85a2-7380-94ff-6d5de79a68a1")
        ),
        "recovered_to_correct_tool": OfflineScorer(
            kind="boolean", version=UUID("01a1557e-f33b-7e99-9408-f3548316c76f")
        ),
        "rendered_entity_ui": OfflineScorer(kind="boolean", version=UUID("01a1557d-f13a-7eda-8447-e54d0ea0e7b1")),
        "search_recovery_after_zero_hit": OfflineScorer(
            kind="boolean", version=UUID("01a1557e-dedb-70fc-a4a4-c8be5f7c4939")
        ),
        "skill_answer_correctness": OfflineScorer(kind="boolean", version=UUID("01a1557e-e9b1-79b4-82c4-3639a73a9d66")),
        "skill_loaded_before_tool": OfflineScorer(kind="boolean", version=UUID("01a1557e-b9d5-7cb3-9136-2a8176f7a8f3")),
        "skill_search_first": OfflineScorer(kind="boolean", version=UUID("01a1557e-2b07-7fd6-95ed-e1f5cc459aff")),
        "used_json_output_format": OfflineScorer(kind="boolean", version=UUID("01a1557f-7ce7-7ee9-8a62-0d219935a7cf")),
        "verified_event_before_query": OfflineScorer(
            kind="boolean", version=UUID("01a1557f-8e04-7c10-a084-3bcd95fd5fe8")
        ),
    },
    "cohorts": {
        "cohort_from_query_used": OfflineScorer(kind="boolean", version=UUID("01a1557f-a2a9-7cd5-a647-24fbc34fdaca")),
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1557f-974a-79e8-a589-a41e4ff8bf2d")),
        "no_uuid_batching": OfflineScorer(kind="boolean", version=UUID("01a1557f-bbad-7dcc-b140-d5c1fe69a9d2")),
        "query_targets_actor_column": OfflineScorer(
            kind="boolean", version=UUID("01a1557f-b048-7ebe-8db4-2d89aa79787e")
        ),
    },
    "data_warehouse": {
        "agentic_search_used": OfflineScorer(kind="boolean", version=UUID("01a1557f-db0e-76f5-ade3-847fb199d132")),
        "answer_query_ran": OfflineScorer(kind="boolean", version=UUID("01a15580-3330-7033-a26b-bd7241292083")),
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1557f-c598-76ff-8312-e8261f7357c2")),
        "information_schema_before_answer": OfflineScorer(
            kind="boolean", version=UUID("01a1557f-efac-7e78-b26d-3c45cab69449")
        ),
        "information_schema_queried": OfflineScorer(
            kind="boolean", version=UUID("01a1557f-d0c7-7e57-9845-8c4b1f4d3004")
        ),
        "join_path_traversed": OfflineScorer(kind="boolean", version=UUID("01a15580-55a9-77a1-9815-f898ba72b96a")),
        "needle_table_identified": OfflineScorer(kind="boolean", version=UUID("01a1557f-e4dc-75a1-9606-24647018c5c5")),
        "needle_value_retrieved": OfflineScorer(kind="boolean", version=UUID("01a15580-29c9-7d6e-afa2-c650a1958662")),
        "relationship_discovery": OfflineScorer(kind="boolean", version=UUID("01a15580-452b-7ccd-9a91-d87dace78770")),
        "stale_table_avoided": OfflineScorer(kind="boolean", version=UUID("01a15580-5f0c-7e20-baca-eb544aba6950")),
        "warehouse_answer_correctness": OfflineScorer(
            kind="numeric", version=UUID("01a15580-3c17-77bc-af79-dfb04a075815")
        ),
    },
    "error_tracking": {
        "events_args_alignment": OfflineScorer(kind="boolean", version=UUID("01a15580-83eb-7edb-88ed-e3a278c1bad6")),
        "events_tool_used": OfflineScorer(kind="boolean", version=UUID("01a15580-7acc-7e5b-bb9c-6e670b54e66d")),
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a15580-67d1-7a2c-bdfe-d4de0553020c")),
        "issue_drilldown_order": OfflineScorer(kind="boolean", version=UUID("01a15580-9762-7200-b518-2da4b1d854ce")),
        "issue_id_matches_target": OfflineScorer(kind="boolean", version=UUID("01a15580-8e80-70df-b21a-15945ed85bdb")),
        "issue_input_alignment": OfflineScorer(kind="boolean", version=UUID("01a15581-0aec-75b5-b0e7-e371e5853164")),
        "issues_list_input_alignment": OfflineScorer(
            kind="boolean", version=UUID("01a15581-1e2c-7ae1-9522-0f54a9c6e4a9")
        ),
        "issues_list_tool_used": OfflineScorer(kind="boolean", version=UUID("01a15581-148b-74d7-93d7-8c3110ab2a95")),
        "no_error_tracking_write": OfflineScorer(kind="boolean", version=UUID("01a15580-7158-7c13-856a-ff7669b5e0f2")),
    },
    "experiments": {
        "advises_against_shipping": OfflineScorer(kind="boolean", version=UUID("01a1558e-f848-7def-b3d8-970df097d0e5")),
        "asked_for_confirmation": OfflineScorer(kind="boolean", version=UUID("01a1558f-1274-77da-9d79-2e410a63cbbc")),
        "called_experiment_update": OfflineScorer(kind="boolean", version=UUID("01a1558f-1ac0-7176-8fbe-8730bbd9074a")),
        "diagnosis_group": OfflineScorer(kind="boolean", version=UUID("01a1558f-2481-7ab2-95a5-a9f4e7e087eb")),
        "does_not_recommend_edit": OfflineScorer(kind="boolean", version=UUID("01a1558f-314c-7d2f-bf87-43b94f4917ff")),
        "duplicate_unique_flag_key": OfflineScorer(
            kind="boolean", version=UUID("01a1558f-3b7c-7347-8fd2-a2eba94f5723")
        ),
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a1558f-4447-7a87-b21c-4418a4152cc0")),
        "experiment_created_successfully": OfflineScorer(
            kind="boolean", version=UUID("01a1558f-55a3-7584-8fae-39efa8c6b11e")
        ),
        "first_update_metric_shape": OfflineScorer(
            kind="boolean", version=UUID("01a1558f-5ee1-77eb-b837-843569f351b3")
        ),
        "loaded_shared_metric": OfflineScorer(kind="boolean", version=UUID("01a1558f-69dc-7efe-adfe-1debc1acbfa0")),
        "no_silent_update_with_unknown_event": OfflineScorer(
            kind="boolean", version=UUID("01a1558f-71f0-74a5-aec8-a03922367ecc")
        ),
        "no_unconfirmed_ship": OfflineScorer(kind="boolean", version=UUID("01a1558f-7d13-7a20-9035-2aa9cdddb4ac")),
        "recommends_ship_variant": OfflineScorer(kind="boolean", version=UUID("01a1558f-8617-7a83-87a2-27f3adf7d54a")),
        "resolved_experiment_by_name": OfflineScorer(
            kind="boolean", version=UUID("01a1558f-8e45-7480-b669-ae4c5d655366")
        ),
        "shared_metric_validation_verdict": OfflineScorer(
            kind="boolean", version=UUID("01a1558f-9a54-7743-905c-bb10f59c3264")
        ),
        "skill_loaded": OfflineScorer(kind="boolean", version=UUID("01a1558f-a299-7e75-938e-07c2ff9c747f")),
        "surfaces_all_findings": OfflineScorer(kind="boolean", version=UUID("01a1558f-ad52-7b81-8a93-d7e602bf0125")),
    },
    "product_analytics": {
        "answer_tool_call_not_forbidden": OfflineScorer(
            kind="boolean", version=UUID("01a15a27-7d06-768b-940c-f47b5f3ee78c")
        ),
        "did_not_cite_raw_sql_after_typed_query": OfflineScorer(
            kind="boolean", version=UUID("01a15a27-735b-700b-9f5b-51533df620b3")
        ),
        "no_markdown_data_table": OfflineScorer(kind="boolean", version=UUID("01a15a27-69b4-7bc0-b6f6-b366acc272b2")),
        "chart_from_typed_query": OfflineScorer(kind="boolean", version=UUID("01a16420-8c66-7f91-9939-997516aafc3b")),
        "chart_shown": OfflineScorer(kind="boolean", version=UUID("01a16420-30a5-770e-a4f3-16ff4f7dcb84")),
        "answer_from_typed_query": OfflineScorer(kind="boolean", version=UUID("01a15a27-4bce-7e6c-b3ef-34d292489b30")),
        "answer_tool_not_execute_sql": OfflineScorer(
            kind="boolean", version=UUID("01a15581-3926-7c14-a907-e994586bd216")
        ),
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a15581-2721-7343-9ee8-d4cb29adbe1a")),
        "first_relevant_tool": OfflineScorer(kind="boolean", version=UUID("01a15581-9357-7433-89c5-b66294e872d5")),
        "first_relevant_tool_t1": OfflineScorer(kind="boolean", version=UUID("01a15581-bca9-7af2-a9e1-fd29a55c7291")),
        "first_relevant_tool_t2": OfflineScorer(kind="boolean", version=UUID("01a15581-c7a2-7706-9d55-f2bd6640b817")),
        "first_relevant_tool_t3": OfflineScorer(kind="boolean", version=UUID("01a15581-d0cf-7b8a-ae3f-558eb875af9c")),
        "first_relevant_tool_t4": OfflineScorer(kind="boolean", version=UUID("01a15581-db3d-7eb7-8184-ef777d8900c1")),
        "funnel_schema_alignment": OfflineScorer(kind="numeric", version=UUID("01a15581-4c67-7321-bad6-608fbbe18564")),
        "funnel_time_range_relevancy": OfflineScorer(
            kind="boolean", version=UUID("01a15581-5652-79d8-a3b0-48be756495eb")
        ),
        "insight_shape": OfflineScorer(kind="boolean", version=UUID("01a15581-e3df-7304-b06e-8ae4ad58ccf5")),
        "no_persistent_insight_save": OfflineScorer(
            kind="boolean", version=UUID("01a15581-2fc3-7c68-b349-d44a670b232d")
        ),
        "providing_insights_skill_loaded": OfflineScorer(
            kind="boolean", version=UUID("01a15581-9c84-7f36-837a-e20bbb99ac17")
        ),
        "retention_schema_alignment": OfflineScorer(
            kind="numeric", version=UUID("01a15581-5faa-7855-b46a-90ff034dae82")
        ),
        "retention_time_range_relevancy": OfflineScorer(
            kind="boolean", version=UUID("01a15581-6891-7f9b-bbb4-199b8b2edec0")
        ),
        "saved_insight": OfflineScorer(kind="boolean", version=UUID("01a15581-ee89-7754-b0dd-6012efeaa1c4")),
        "schema_discovery_order": OfflineScorer(kind="boolean", version=UUID("01a15581-7429-7fff-85a7-9c223feddee6")),
        "trends_schema_alignment": OfflineScorer(kind="numeric", version=UUID("01a15581-a78c-7d03-bb2d-de43ab247f81")),
        "trends_time_range_relevancy": OfflineScorer(
            kind="boolean", version=UUID("01a15581-b135-7a70-ae09-b3d0e93bc894")
        ),
        "verified_event_exists": OfflineScorer(kind="boolean", version=UUID("01a15581-41af-7c8a-bf72-5e7c4ef63b0b")),
    },
    "retrieval": {
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a15581-f842-7336-8237-f5a8bf96d317")),
        "info_before_execute_sql": OfflineScorer(kind="boolean", version=UUID("01a15582-4169-7666-8583-809f548f5ee7")),
        "information_schema_before_sql": OfflineScorer(
            kind="boolean", version=UUID("01a15582-3921-7c7f-9066-b2e9a767cd33")
        ),
        "lookup_id_in_output": OfflineScorer(kind="boolean", version=UUID("01a15582-2caf-725e-b7f0-ac9a02218b09")),
        "skill_loaded": OfflineScorer(kind="boolean", version=UUID("01a15582-0134-7aaa-b171-52e5fb222bfa")),
    },
    "sql": {
        "answer_tool_not_typed_query": OfflineScorer(
            kind="boolean", version=UUID("01a11725-3002-7a3f-b9b5-3426bdec5f00")
        ),
        "execute_sql_called": OfflineScorer(kind="boolean", version=UUID("01a11725-20aa-78c3-af96-1aae34bca429")),
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a11724-d52d-704a-af08-2ceaf5c65a6d")),
        "no_persistent_insight_save": OfflineScorer(
            kind="boolean", version=UUID("01a11725-17f6-7673-93e9-4d525fa121ab")
        ),
        "querying_posthog_data_skill_loaded": OfflineScorer(
            kind="boolean", version=UUID("01a11725-54c1-71e0-b606-132d5f4cb339")
        ),
        "sql_result_message_alignment": OfflineScorer(
            kind="numeric", version=UUID("01a11725-6940-7f49-b979-11b3d6521393")
        ),
        "sql_schema_alignment": OfflineScorer(kind="numeric", version=UUID("01a11725-5da7-7dae-ab09-1c0beaa77224")),
    },
    "surveys": {
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a15582-4a50-75e1-a17a-3d483bb95586")),
        "no_forbidden_survey_side_effects": OfflineScorer(
            kind="boolean", version=UUID("01a15582-5371-7f81-8356-53532c73fac2")
        ),
        "survey_create_alignment": OfflineScorer(kind="numeric", version=UUID("01a15582-711a-7b7a-bd93-061a83ea909d")),
        "survey_create_outcome": OfflineScorer(kind="boolean", version=UUID("01a15582-5d5a-786a-965f-ee2075db057d")),
        "survey_create_returned_id": OfflineScorer(
            kind="boolean", version=UUID("01a15582-6656-7fb2-b67d-6b918a8363e0")
        ),
        "survey_id_in_final_message": OfflineScorer(
            kind="boolean", version=UUID("01a15582-7cea-7b35-9632-1fd1c3e22185")
        ),
    },
    "turn_suggestions": {
        "offer_correctness": OfflineScorer(kind="boolean", version=UUID("01a15a29-ea9e-743e-9a21-cec75e5e417e")),
    },
    "taxonomic_filter": {
        "event_match_found": OfflineScorer(kind="boolean", version=UUID("01a15582-8f96-76a8-a6b0-9ad9c932f12a")),
        "exit_code_zero": OfflineScorer(kind="boolean", version=UUID("01a15582-85bb-71aa-b4c8-dc008015ab30")),
        "no_wrong_event_match": OfflineScorer(kind="boolean", version=UUID("01a15582-9ce5-711e-b612-3b0be41c2669")),
        "no_wrong_switch": OfflineScorer(kind="boolean", version=UUID("01a15582-b862-766e-b1ee-6664b70a9a93")),
        "search_intent_match": OfflineScorer(kind="boolean", version=UUID("01a15582-a5dd-7f46-8681-5f0dd77b22d4")),
        "switch_when_needed": OfflineScorer(kind="boolean", version=UUID("01a15582-aef0-748b-8282-c92f901762b5")),
    },
}


def offline_suite(key: str, *, metrics: Sequence[str], suite_kind: SuiteKind = SuiteKind.SANDBOXED) -> OfflineEvalSuite:
    domain = key.split("/", 1)[0]
    scorers = _SCORERS[domain]
    component = domain.replace("_", "-")
    enrolled_metrics = ("exit_code_zero", *metrics) if suite_kind == SuiteKind.SANDBOXED else metrics
    return OfflineEvalSuite.from_scorers(
        key=key,
        project_id=2,
        scorers={metric: scorers[metric] for metric in enrolled_metrics},
        tags=("team:surfaces", f"component:posthog-ai/{component}"),
    )
