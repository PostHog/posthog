"""Per-connector table names, config keys and caveats for a Fivetran migration.

Fivetran table names come from each connector's published schema reference at
`https://fivetran.com/docs/connectors/applications/<connector>/connector-schema.md`. The HubSpot
`engagement_*` and Bing Ads names come from Fivetran's dbt source packages at
`https://github.com/fivetran/dbt_<connector>`, because connections set up before the current
schema still have those tables. An alias
names the PostHog table that holds the same records. A Fivetran table with no alias and no
PostHog table of the same name has no PostHog equivalent.
"""

from collections.abc import Mapping

_STRIPE = {
    "application_fee": "ApplicationFee",
    "balance_transaction": "BalanceTransaction",
    "billing_meter": "BillingMeter",
    "charge": "Charge",
    "checkout_session": "CheckoutSession",
    "coupon": "Coupon",
    "credit_grant": "BillingCreditGrant",
    "credit_note": "CreditNote",
    "customer": "Customer",
    "customer_balance_transaction": "CustomerBalanceTransaction",
    "discount": "Discount",
    "dispute": "Dispute",
    "early_fraud_warning": "EarlyFraudWarning",
    "invoice": "Invoice",
    "invoice_item": "InvoiceItem",
    "invoice_payment": "InvoicePayment",
    "payment_intent": "PaymentIntent",
    "payment_link": "PaymentLink",
    "payment_method": "CustomerPaymentMethod",
    "payout": "Payout",
    "plan": "Plan",
    "price": "Price",
    "product": "Product",
    "promotion_code": "PromotionCode",
    "quote": "Quote",
    "refund": "Refund",
    "review": "Review",
    "setup_attempt": "SetupAttempt",
    "setup_intent": "SetupIntent",
    "shipping_rate": "ShippingRate",
    "subscription": "Subscription",
    "subscription_history": "Subscription",
    "subscription_item": "SubscriptionItem",
    "subscription_schedule": "SubscriptionSchedule",
    "tax_rate": "TaxRate",
    "topup": "Topup",
    "transfer": "Transfer",
}

_HUBSPOT = {
    "company": "companies",
    "contact": "contacts",
    "deal": "deals",
    "deal_pipeline": "pipelines",
    "deal_pipeline_stage": "pipeline_stages",
    "engagement_call": "calls",
    "engagement_communication": "communications",
    "engagement_email": "emails",
    "engagement_meeting": "meetings",
    "engagement_note": "notes",
    "engagement_task": "tasks",
    "feedback_submission": "feedback_submissions",
    "invoice": "invoices",
    "lead": "leads",
    "line_item": "line_items",
    "order": "orders",
    "owner": "owners",
    "payment": "commerce_payments",
    "product": "products",
    "property": "properties",
    "quote": "quotes",
    "subscription": "subscriptions",
    "ticket": "tickets",
    "ticket_pipeline": "pipelines",
    "ticket_pipeline_stage": "pipeline_stages",
}

# Fivetran names Salesforce tables by snake-casing the object API name.
_SALESFORCE = {
    "account": "Account",
    "campaign": "Campaign",
    "contact": "Contact",
    "event": "Event",
    "lead": "Lead",
    "opportunity": "Opportunity",
    "opportunity_history": "OpportunityHistory",
    "order": "Order",
    "pricebook_2": "Pricebook2",
    "pricebook_entry": "PricebookEntry",
    "product_2": "Product2",
    "task": "Task",
    "user": "User",
    "user_role": "UserRole",
}

_ZENDESK = {
    "audit_log": "audit_logs",
    "automation": "automations",
    "brand": "brands",
    "custom_role": "custom_roles",
    "group": "groups",
    "group_member": "group_memberships",
    "macro": "macros",
    "organization": "organizations",
    "organization_member": "organization_memberships",
    "satisfaction_rating": "satisfaction_ratings",
    "sla_policy_history": "sla_policies",
    "suspended_ticket": "suspended_tickets",
    "ticket": "tickets",
    "ticket_comment": "ticket_comments",
    "ticket_form_history": "ticket_forms",
    "trigger": "triggers",
    "user": "users",
}

_SHOPIFY = {
    "abandoned_checkout": "abandonedCheckouts",
    "catalog": "catalogs",
    "collection": "collections",
    "customer": "customers",
    "discount_code": "discountCodes",
    "order": "orders",
    "product": "products",
}

_GOOGLE_ADS = {
    "account_history": "customer",
    "account_stats": "customer_stats",
    "ad_group_criterion_history": "ad_group_criterion",
    "ad_group_history": "ad_group",
    "ad_history": "ad",
    "campaign_budget_history": "campaign_budget",
    "campaign_criterion_history": "campaign_criterion",
    "campaign_history": "campaign",
    "search_term_keyword_stats": "search_term_stats",
}

_FACEBOOK_ADS = {
    "account_history": "ad_account",
    "ad_history": "ads",
    "ad_image_history": "ad_images",
    "ad_set_history": "adsets",
    "basic_ad": "ad_stats",
    "campaign_history": "campaigns",
    "creative_history": "ad_creatives",
    "custom_conversion_history": "custom_conversions",
}

_LINKEDIN_ADS = {
    "account_history": "accounts",
    "ad_analytics_by_campaign": "campaign_stats",
    "ad_analytics_by_creative": "creative_stats",
    "campaign_group_history": "campaign_groups",
    "campaign_history": "campaigns",
    "conversion_history": "conversions",
    "creative_history": "creatives",
}

_INTERCOM = {
    "admin": "admins",
    "admin_activity_log": "activity_logs",
    "article_history": "articles",
    "collection_history": "collections",
    "company_history": "companies",
    "company_segment_history": "company_segments",
    "contact_history": "contacts",
    "conversation_history": "conversations",
    "conversation_part_history": "conversation_parts",
    "help_center_history": "help_centers",
    "news_item_history": "news_items",
    "newsfeed_history": "newsfeeds",
    "segment": "segments",
    "subscription_type": "subscription_types",
    "tag": "tags",
    "team": "teams",
    "ticket_history": "tickets",
    "ticket_state": "ticket_states",
    "ticket_type_history": "ticket_types",
}

_JIRA = {
    "board": "boards",
    "comment": "issue_comments",
    "field": "fields",
    "issue": "issues",
    "issue_type": "issue_types",
    "priority": "priorities",
    "project": "projects",
    "resolution": "resolutions",
    "sprint": "sprints",
    "status": "statuses",
    "user": "users",
    "version": "versions",
    "worklog": "worklogs",
}

_KLAVIYO = {
    "account_history": "accounts",
    "coupon": "coupons",
    "coupon_code": "coupon_codes",
    "email_template": "templates",
    "event": "events",
    "flow": "flows",
    "flow_action": "flow_actions",
    "flow_message": "flow_messages",
    "form": "forms",
    "list": "lists",
    "list_person": "list_profiles",
    "metric": "metrics",
    "person": "profiles",
    "push_token": "push_tokens",
    "segment": "segments",
    "segment_person": "segment_profiles",
    "tag_group": "tag_groups",
}

_MAILCHIMP = {
    "automation": "automations",
    "automation_email": "automation_emails",
    "campaign": "campaigns",
    "campaign_report": "reports",
    "interest_category": "list_interest_categories",
    "list": "lists",
    "member": "contacts",
    "orders": "ecommerce_orders",
    "product": "ecommerce_products",
    "segment": "list_segments",
    "segment_member": "list_segment_members",
    "store": "ecommerce_stores",
}

_ASANA = {
    "custom_field": "custom_fields",
    "goal": "goals",
    "goal_status": "goal_status_updates",
    "portfolio": "portfolios",
    "portfolio_item": "portfolio_items",
    "project": "projects",
    "project_status": "project_status_updates",
    "section": "sections",
    "story": "stories",
    "tag": "tags",
    "task": "tasks",
    "team": "teams",
    "time_tracking": "time_tracking_entries",
    "user": "users",
    "workspace": "workspaces",
}

_PIPEDRIVE = {
    "activity": "activities",
    "deal_field": "deal_fields",
    "deal_history": "deals",
    "lead_history": "leads",
    "note": "notes",
    "organization": "organizations",
    "person": "persons",
    "pipeline": "pipelines",
    "product": "products",
    "stage": "stages",
    "user": "users",
}

_FRESHDESK = {
    "agent": "agents",
    "business_hour": "business_hours",
    "company": "companies",
    "contact": "contacts",
    "conversation": "conversations",
    "group": "groups",
    "product": "products",
    "role": "roles",
    "satisfaction_rating": "satisfaction_ratings",
    "sla_policy": "sla_policies",
    "solution_article": "solution_articles",
    "solution_category": "solution_categories",
    "solution_folder": "solution_folders",
    "ticket_field": "ticket_fields",
    "ticket_history": "tickets",
}

_MIXPANEL = {
    "event": "export",
    "people": "engage",
}

_AMPLITUDE = {
    "event": "events",
    "event_type": "event_types",
}

_TIKTOK_ADS = {
    "ad_history": "ads",
    "adgroup_history": "ad_groups",
    "campaign_history": "campaigns",
    "image_history": "creative_images",
    "video_history": "creative_videos",
}

_BING_ADS = {
    "ad_group_performance_daily_report": "ad_group_performance_report",
    "ad_performance_daily_report": "ad_performance_report",
    "campaign_history": "campaigns",
    "campaign_performance_daily_report": "campaign_performance_report",
    "keyword_performance_daily_report": "keyword_performance_report",
}

_GOOGLE_SEARCH_CONSOLE = {
    "keyword_page_report": "search_analytics_by_query_page",
    "keyword_site_report_by_site": "search_analytics_by_query",
    "page_report": "search_analytics_by_page",
    "site_report_by_site": "search_analytics_by_country_device",
    "sitemap": "sitemaps",
}

_SENDGRID = {
    "single_send": "singlesends",
    "unsubscribe_group": "unsubscribe_groups",
}

_RECURLY = {
    "account_acquisition_history": "acquisitions",
    "account_history": "accounts",
    "coupon_history": "coupons",
    "coupon_redemption_history": "coupon_redemptions",
    "credit_payment_history": "credit_payments",
    "external_subscription": "external_subscriptions",
    "gift_card": "gift_cards",
    "invoice_history": "invoices",
    "line_item_history": "line_items",
    "plan_add_on_history": "add_ons",
    "plan_history": "plans",
    "subscription_history": "subscriptions",
    "transaction": "transactions",
    "usage_record": "usage",
}

_GITLAB = {
    "project_branch": "branches",
    "project_commit": "commits",
    "project_issue": "issues",
    "project_job": "jobs",
    "project_label": "labels",
    "project_member": "members",
    "project_merge_request": "merge_requests",
    "project_merge_request_discussion_note": "merge_request_notes",
    "project_milestone": "milestones",
    "project_pipeline": "pipelines",
    "project_release": "releases",
    "project_repo_tag": "tags",
}

_SENTRY = {
    "issue_event": "issue_events",
    "organization_release": "releases",
    "organization_repository": "repos",
    "organization_team": "teams",
    "project": "projects",
    "project_error_event": "project_events",
    "project_issue": "issues",
    "project_service_hook": "project_service_hooks",
    "project_user": "project_users",
    "repository_commit": "repo_commits",
}

_ITERABLE = {
    "campaign_history": "campaigns",
    "channel": "channels",
    "list": "lists",
    "list_user": "list_users",
    "list_user_history": "list_users",
    "message_type": "message_types",
    "template_history": "templates",
    "user_history": "users",
}

_BRAZE = {
    "campaign": "campaigns",
    "canvas": "canvases",
    "segment": "segments",
}

_PINTEREST_ADS = {
    "ad_group_history": "ad_groups",
    "ad_group_report": "ad_group_analytics",
    "advertiser_history": "ad_accounts",
    "audience_history": "audiences",
    "campaign_history": "campaigns",
    "campaign_report": "campaign_analytics",
    "conversion_tag_history": "conversion_tags",
    "keyword_history": "keywords",
    "pin_promotion_history": "ads",
    "pin_promotion_report": "ad_analytics",
}

_SNAPCHAT_ADS = {
    "ad_account_history": "ad_accounts",
    "ad_history": "ads",
    "ad_squad_history": "ad_squads",
    "audience_segment_history": "audience_segments",
    "campaign_history": "campaigns",
    "creative_history": "creatives",
    "media_history": "media",
    "snap_pixel_history": "pixels",
}

FIVETRAN_TABLE_ALIASES: Mapping[str, Mapping[str, str]] = {
    "amplitude": _AMPLITUDE,
    "asana": _ASANA,
    "bingads": _BING_ADS,
    "braze": _BRAZE,
    "facebook_ads": _FACEBOOK_ADS,
    "freshdesk": _FRESHDESK,
    "gitlab": _GITLAB,
    "google_ads": _GOOGLE_ADS,
    "google_search_console": _GOOGLE_SEARCH_CONSOLE,
    "hubspot": _HUBSPOT,
    "intercom": _INTERCOM,
    "iterable": _ITERABLE,
    "jira": _JIRA,
    "klaviyo": _KLAVIYO,
    "linkedin_ads": _LINKEDIN_ADS,
    "mailchimp": _MAILCHIMP,
    "mixpanel": _MIXPANEL,
    "pinterest_ads": _PINTEREST_ADS,
    "pipedrive": _PIPEDRIVE,
    "recurly": _RECURLY,
    "salesforce": _SALESFORCE,
    "salesforce_sandbox": _SALESFORCE,
    "sendgrid": _SENDGRID,
    "sentry": _SENTRY,
    "shopify": _SHOPIFY,
    "snapchat_ads": _SNAPCHAT_ADS,
    "stripe": _STRIPE,
    "stripe_test": _STRIPE,
    "tiktok_ads": _TIKTOK_ADS,
    "zendesk": _ZENDESK,
}

_TUNNEL = {
    "tunnel_host": "ssh_tunnel.host",
    "tunnel_port": "ssh_tunnel.port",
    "tunnel_user": "ssh_tunnel.auth.username",
}
_SQL_DATABASE = {"host": "host", "port": "port", "database": "database", "user": "user", **_TUNNEL}

_POSTGRES_SERVICES = (
    "aurora_postgres",
    "azure_postgres",
    "google_cloud_postgresql",
    "heroku_postgres",
    "postgres",
    "postgres_rds",
)
_MYSQL_SERVICES = (
    "aurora",
    "google_cloud_mysql",
    "magento_mysql",
    "magento_mysql_rds",
    "maria",
    "maria_azure",
    "maria_rds",
    "mysql",
    "mysql_azure",
    "mysql_rds",
)
_MSSQL_SERVICES = (
    "azure_sql_db",
    "azure_sql_managed_db",
    "google_cloud_sqlserver",
    "sql_server",
    "sql_server_hva",
    "sql_server_rds",
)

FIVETRAN_CONFIG_KEYS: Mapping[str, Mapping[str, str]] = {
    **dict.fromkeys(_POSTGRES_SERVICES + _MYSQL_SERVICES + _MSSQL_SERVICES, _SQL_DATABASE),
    "snowflake_db": {"database": "database", "role": "role", "user": "auth_type.user"},
    "bigquery_db": {"data_set_name": "dataset_id"},
}

_LOCAL_AGENT_NOTE = (
    "Fivetran reads this database through an agent on your network. "
    "PostHog connects to the database directly, so it must be reachable from PostHog or through an SSH tunnel."
)

FIVETRAN_NOTES: Mapping[str, tuple[str, ...]] = {
    "sql_server_hva": (_LOCAL_AGENT_NOTE,),
    "github": ("PostHog syncs GitHub one repository at a time. Choose the repositories when you connect the source.",),
    "google_search_console": (
        "PostHog's query and page tables do not break down by country and device like the Fivetran reports do.",
    ),
    "google_analytics_4": (
        "PostHog syncs a fixed set of Google Analytics reports. Fivetran custom reports do not move over.",
    ),
    "azure_cosmos_for_mongo": ("PostHog reads Cosmos DB for MongoDB with its MongoDB source.",),
}
