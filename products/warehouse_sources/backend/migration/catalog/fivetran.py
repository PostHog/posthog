"""Fivetran-specific exceptions to the name-based matching rules in `catalog/__init__.py`.

Keep this file to the cases a rule cannot get right. A missing override or rewrite leaves the
connector or table unmatched, and the user and the agent choose what to do. A missing rejection
is not safe: it lets a different product of the same name match.
"""

from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.types import ExternalDataSourceType as T

# Fivetran service ids that name matching cannot pair with their PostHog source, or pairs wrongly.
SOURCE_OVERRIDES: dict[str, T] = {
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
    # A name match gives the PostHog Confluent Cloud source, which reads the Metrics API, not topics.
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
    "double_click_publishers": T.GOOGLEADMANAGER,
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
REJECTED_SOURCES: frozenset[str] = frozenset(
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


# Fivetran table name endings and what to try in their place. A history-mode table such as Google Ads
# `campaign_history` holds the same records as `campaigns`, and `campaign_performance_daily_report`
# as `campaign_performance_report`. The match is only inferred, because some `_history` tables are
# audit logs instead.
# A plain `_report` ending stays, because `campaign_report` holds metrics, not the records in `campaigns`.
TABLE_SUFFIX_REWRITES: tuple[tuple[str, str], ...] = (
    ("_history", ""),
    ("_daily_report", "_report"),
)

# Fivetran keeps the SSH tunnel in flat config keys. PostHog nests it under the `ssh_tunnel` field.
TUNNEL_CONFIG_KEYS: dict[str, str] = {
    "tunnel_host": "ssh_tunnel.host",
    "tunnel_port": "ssh_tunnel.port",
    "tunnel_user": "ssh_tunnel.auth.username",
}

# Non-secret config keys whose PostHog field has a different name. Keys with the same name on both
# sides are copied without an entry here.
CONFIG_KEY_OVERRIDES: dict[T, dict[str, str]] = {
    T.SNOWFLAKE: {"user": "auth_type.user"},
    T.BIGQUERY: {"data_set_name": "dataset_id"},
}

_D = ExternalDataDestination.Type

# Fivetran destination service ids, from
# https://github.com/fivetran/terraform-provider-fivetran/blob/main/destination-services.txt.
# The managed data lake is left out because it can sit on ADLS or GCS, which an S3 destination cannot write to.
DESTINATION_TYPES: dict[str, ExternalDataDestination.Type] = {
    "snowflake": _D.SNOWFLAKE,
    "big_query": _D.BIGQUERY,
    "big_query_dts": _D.BIGQUERY,
    "managed_big_query": _D.BIGQUERY,
    "redshift": _D.REDSHIFT,
    "aurora_postgres_warehouse": _D.POSTGRES,
    "azure_postgres_warehouse": _D.POSTGRES,
    "postgres_databricks_warehouse": _D.POSTGRES,
    "postgres_gcp_warehouse": _D.POSTGRES,
    "postgres_rds_warehouse": _D.POSTGRES,
    "postgres_warehouse": _D.POSTGRES,
    "postgres_wh": _D.POSTGRES,
    "databricks": _D.DATABRICKS,
    "databricks_via_managed_data_lake": _D.DATABRICKS,
}
