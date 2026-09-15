import pytest

from products.growth.backend.facade import dags


@pytest.mark.parametrize(
    "module_name,definition,expected_name",
    [
        ("ai_enrichment", "ai_enrichment_job", "ai_enrichment_job"),
        ("ai_enrichment", "ai_enrichment_schedule", "ai_enrichment_schedule"),
        ("custom_product_push_campaigns", "custom_product_push_campaigns_job", "custom_product_push_campaigns_job"),
        ("github_sdk_versions", "cache_github_sdk_versions_job", "cache_github_sdk_versions_job"),
        ("github_sdk_versions", "cache_github_sdk_versions_schedule", "cache_github_sdk_versions_schedule"),
        ("identity_matching", "identity_matching_job", "identity_matching_job"),
        ("oauth", "oauth_clear_expired_oauth_tokens_job", "oauth_clear_expired_oauth_tokens_job"),
        ("oauth", "oauth_clear_expired_oauth_tokens_schedule", "oauth_cleanup_daily_schedule"),
        ("product_push_campaigns", "product_push_campaigns_job", "product_push_campaigns_job"),
        ("product_push_campaigns", "product_push_campaigns_schedule", "product_push_campaigns_schedule"),
        (
            "team_production_event_activation",
            "detect_first_team_production_event_job",
            "detect_first_team_production_event_job",
        ),
        (
            "team_production_event_activation",
            "detect_first_team_production_event_schedule",
            "detect_first_team_production_event_schedule",
        ),
    ],
)
def test_facade_exposes_the_growth_dagster_definitions_under_their_registered_names(
    module_name: str, definition: str, expected_name: str
) -> None:
    module = getattr(dags, module_name)

    assert module.__name__ == f"products.growth.dags.{module_name}"
    assert getattr(module, definition).name == expected_name


def test_facade_exports_exactly_the_modules_the_growth_code_location_loads() -> None:
    assert sorted(dags.__all__) == [
        "ai_enrichment",
        "custom_product_push_campaigns",
        "github_sdk_versions",
        "identity_matching",
        "oauth",
        "product_push_campaigns",
        "team_production_event_activation",
    ]
