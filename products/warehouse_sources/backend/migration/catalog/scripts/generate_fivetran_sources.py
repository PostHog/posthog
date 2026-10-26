"""Generate `catalog/fivetran_sources.py`, the Fivetran service id to PostHog source type map.

Fivetran's connector type endpoint needs an API key, so the input is the service id list that
Fivetran publishes with its Terraform provider. Download it, then run from the repo root:

    curl -o /tmp/fivetran_services.txt \
        https://raw.githubusercontent.com/fivetran/terraform-provider-fivetran/main/services.txt
    PYTHONPATH=. python products/warehouse_sources/backend/migration/catalog/scripts/generate_fivetran_sources.py \
        /tmp/fivetran_services.txt
    ruff format products/warehouse_sources/backend/migration/catalog/fivetran_sources.py

A service id matches a source type when both reduce to the same letters (`google_ads` and
`GoogleAds`). `_EXTRA_MATCHES` adds the pairs that name matching cannot find, and `_REJECTED`
removes name matches that point at a different product of the same vendor.
"""

import sys
from pathlib import Path

from products.warehouse_sources.backend.types import ExternalDataSourceType as T

_OUTPUT = Path(__file__).resolve().parent.parent / "fivetran_sources.py"

_EXTRA_MATCHES: dict[str, T] = {
    # Hosted and managed flavors of the same database engine.
    "aurora_postgres": T.POSTGRES,
    "azure_postgres": T.POSTGRES,
    "google_cloud_postgresql": T.POSTGRES,
    "heroku_postgres": T.POSTGRES,
    "postgres_rds": T.POSTGRES,
    "aurora": T.MYSQL,
    "google_cloud_mysql": T.MYSQL,
    "magento_mysql": T.MYSQL,
    "magento_mysql_rds": T.MYSQL,
    "maria": T.MYSQL,
    "maria_azure": T.MYSQL,
    "maria_rds": T.MYSQL,
    "mysql_azure": T.MYSQL,
    "mysql_rds": T.MYSQL,
    "azure_sql_db": T.MSSQL,
    "azure_sql_managed_db": T.MSSQL,
    "google_cloud_sqlserver": T.MSSQL,
    "sql_server": T.MSSQL,
    "sql_server_hva": T.MSSQL,
    "sql_server_rds": T.MSSQL,
    "oracle_hva": T.ORACLE,
    "oracle_rac": T.ORACLE,
    "oracle_rds": T.ORACLE,
    "db2i_hva": T.DB2,
    "db2luw": T.DB2,
    "db2z": T.DB2,
    "mongo": T.MONGODB,
    "mongo_sharded": T.MONGODB,
    "azure_cosmos_for_mongo": T.MONGODB,
    "cosmos": T.COSMOSDB,
    "documentdb": T.AWSDOCUMENTDB,
    "sap_hana_db": T.SAPHANA,
    "bigquery_db": T.BIGQUERY,
    "databricks_db": T.DATABRICKS,
    "planetscale": T.PLANETSCALEMYSQL,
    "singlestore_source": T.SINGLESTORE,
    "snowflake_db": T.SNOWFLAKE,
    "apache_kafka": T.KAFKA,
    "confluent_cloud": T.KAFKA,
    "aws_msk": T.KAFKA,
    "heroku_kafka": T.KAFKA,
    "kinesis": T.AMAZONKINESIS,
    "elastic_cloud": T.ELASTICSEARCH,
    "elastic_cloud_serverless": T.ELASTICSEARCH,
    "es_self_hosted": T.ELASTICSEARCH,
    # File storage.
    "azure_blob_storage": T.AZUREBLOB,
    "gcs": T.GOOGLECLOUDSTORAGE,
    "s3": T.AMAZONS3,
    # Sandbox and test accounts of a vendor use the same PostHog source.
    "braintree_sandbox": T.BRAINTREE,
    "pardot_sandbox": T.PARDOT,
    "paypal_sandbox": T.PAYPAL,
    "salesforce_sandbox": T.SALESFORCE,
    "stripe_test": T.STRIPE,
    "zuora_sandbox": T.ZUORA,
    # Same product under a different or older name.
    "anthropic_claude": T.ANTHROPIC,
    "autodesk_bim_360": T.AUTODESKCONSTRUCTIONCLOUD,
    "atlassian_ops_genie": T.OPSGENIE,
    "aws_cost_report": T.AWSCOSTANDUSAGEREPORT,
    "bigin_by_zoho_crm": T.ZOHOBIGIN,
    "business_central": T.DYNAMICS365BUSINESSCENTRAL,
    "canvas_by_instructure": T.CANVASLMS,
    "ceridian_dayforce": T.DAYFORCE,
    "chargebee_product_catalog_1": T.CHARGEBEE,
    "chargebee_product_catalog_2": T.CHARGEBEE,
    "checkout": T.CHECKOUTCOM,
    "chorusai": T.CHORUS,
    "circle_community_platform": T.CIRCLESO,
    "cj_commission_detail": T.COMMISSIONJUNCTION,
    "concur": T.SAPCONCUR,
    "dbt_cloud": T.DBT,
    "double_click_campaign_manager": T.CAMPAIGNMANAGER360,
    "facebook_ads": T.METAADS,
    "float": T.FLOATAPP,
    "freshdesk_contact_center": T.FRESHCALLER,
    "gainsight_customer_success": T.GAINSIGHTCS,
    "gainsight_product_experience": T.GAINSIGHTPX,
    "genesys": T.GENESYSCLOUD,
    "gongio": T.GONG,
    "google_analytics_4": T.GOOGLEANALYTICS,
    "google_display_and_video_360": T.DISPLAYVIDEO360,
    "google_play": T.GOOGLEPLAYCONSOLE,
    "google_search_ads_360": T.SEARCHADS360,
    "h_level": T.HIGHLEVEL,
    "instagram_business": T.INSTAGRAM,
    "ironsource": T.IRONSOURCEADS,
    "itunes_connect": T.APPSTORECONNECT,
    "jamf": T.JAMFPRO,
    "lightspeed_retail_xseries": T.LIGHTSPEEDRETAIL,
    "linkedin_company_pages": T.LINKEDINPAGES,
    "looker_source": T.LOOKER,
    "maxio_chargify": T.CHARGIFY,
    "netsuite_suiteanalytics": T.NETSUITE,
    "odoo_native": T.ODOO,
    "oracle_fusion_cloud_apps_crm": T.ORACLEFUSION,
    "oracle_fusion_cloud_apps_fscm": T.ORACLEFUSION,
    "oracle_fusion_cloud_apps_hcm": T.ORACLEFUSION,
    "partnerstack_vendor": T.PARTNERSTACK,
    "pylon_support_platform": T.PYLON,
    "rokt": T.ROKTADS,
    "sigma_computing_source": T.SIGMACOMPUTING,
    "sprout": T.SPROUTSOCIAL,
    "stackadapt_graphql": T.STACKADAPT,
    "the_movie_database": T.TMDB,
    "tiktok_shop_partner_center": T.TIKTOKSHOP,
    "toggl_track": T.TOGGL,
    "workday_hcm": T.WORKDAY,
    "zoho_campaigns": T.ZOHOCAMPAIGN,
}

# Same vendor, different product. Each entry names what the Fivetran connector reads and what the
# PostHog source of the same name reads, so a match would sync none of the customer's data.
_REJECTED: frozenset[str] = frozenset(
    {
        # Fivetran reads the Lightspeed R-Series API. PostHog reads X-Series.
        "light_speed_retail",
        # Fivetran takes in the event stream. PostHog reads workspace config from the Public API.
        "segment",
        # Fivetran takes in the event stream. PostHog reads pipeline health from the BDP Console.
        "snowplow",
        # Fivetran reads Workday RaaS custom reports. PostHog reads the HCM API, which is `workday_hcm`.
        "workday",
    }
)


def _letters(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum())


def build_matches(service_ids: list[str]) -> dict[str, T]:
    by_letters = {_letters(source_type.value): source_type for source_type in T}
    matches: dict[str, T] = {}
    for service_id in service_ids:
        if service_id in _REJECTED:
            continue
        source_type = _EXTRA_MATCHES.get(service_id) or by_letters.get(_letters(service_id))
        if source_type is not None:
            matches[service_id] = source_type
    return matches


def render(matches: dict[str, T]) -> str:
    lines = [
        "# Generated by `scripts/generate_fivetran_sources.py`. Edit the script, not this file.",
        "from products.warehouse_sources.backend.types import ExternalDataSourceType",
        "",
        "FIVETRAN_SOURCE_TYPES: dict[str, ExternalDataSourceType] = {",
        *(f'    "{service_id}": ExternalDataSourceType.{matches[service_id].name},' for service_id in sorted(matches)),
        "}",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    service_ids = [line.strip() for line in Path(sys.argv[1]).read_text().splitlines() if line.strip()]
    unknown = sorted((set(_EXTRA_MATCHES) | _REJECTED) - set(service_ids))
    if unknown:
        sys.exit(f"Not in the Fivetran service list, remove from the script: {', '.join(unknown)}")
    _OUTPUT.write_text(render(build_matches(service_ids)))


if __name__ == "__main__":
    main()
