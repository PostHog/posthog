"""Tables the gateway references in the PostHog Postgres database.

The gateway's role has SELECT only on a per-table allowlist in
posthog-cloud-infra (terraform, users.tf); a query outside it fails in
deployed environments only, since tests mock the database. Land the grant
in every environment before declaring a table here.
``tests/test_required_tables.py`` binds this set to the package's SQL.
"""

REQUIRED_TABLES: frozenset[str] = frozenset(
    {
        # Personal API key authentication
        "posthog_personalapikey",
        "posthog_user",
        # OAuth access token authentication
        "posthog_oauthaccesstoken",
        # Project-scope check
        "posthog_team",
        "posthog_organization",
        "posthog_organizationmembership",
        "ee_accesscontrol",
        "ee_role",
        "ee_rolemembership",
    }
)
