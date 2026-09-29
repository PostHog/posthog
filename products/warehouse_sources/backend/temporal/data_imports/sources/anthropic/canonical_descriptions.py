from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_ADMIN_API_DOCS = "https://platform.claude.com/docs/en/api/admin-api"
_ANALYTICS_API_DOCS = "https://platform.claude.com/docs/en/api/admin/analytics"
_USER_MANAGEMENT_API_DOCS = "https://platform.claude.com/docs/en/api/admin"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "users": {
        "description": "Members of your Anthropic organization.",
        "docs_url": f"{_ADMIN_API_DOCS}/users/list-users",
        "columns": {
            "id": "Unique identifier for the user.",
            "type": 'Object type, always "user".',
            "email": "Email address of the user.",
            "name": "Display name of the user.",
            "role": "Organization role: admin, billing, claude_code_user, developer, or user.",
            "added_at": "RFC 3339 timestamp of when the user joined the organization.",
        },
    },
    "invites": {
        "description": "Pending and historical invitations to join your Anthropic organization.",
        "docs_url": f"{_ADMIN_API_DOCS}/invites/list-invites",
        "columns": {
            "id": "Unique identifier for the invite.",
            "type": 'Object type, always "invite".',
            "email": "Email address the invite was sent to.",
            "role": "Organization role the invited user will receive.",
            "invited_at": "RFC 3339 timestamp of when the invite was created.",
            "expires_at": "RFC 3339 timestamp of when the invite expires.",
            "status": "Invite status: accepted, deleted, expired, or pending.",
        },
    },
    "workspaces": {
        "description": "Workspaces in your Anthropic organization (includes archived workspaces).",
        "docs_url": f"{_ADMIN_API_DOCS}/workspaces/list-workspaces",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "type": 'Object type, always "workspace".',
            "name": "Display name of the workspace.",
            "created_at": "RFC 3339 timestamp of when the workspace was created.",
            "archived_at": "RFC 3339 timestamp of when the workspace was archived, or null if active.",
            "display_color": "Hex color code representing the workspace in the Anthropic Console.",
        },
    },
    "api_keys": {
        "description": "API keys provisioned across your Anthropic organization's workspaces.",
        "docs_url": f"{_ADMIN_API_DOCS}/apikeys/list-api-keys",
        "columns": {
            "id": "Unique identifier for the API key.",
            "type": 'Object type, always "api_key".',
            "name": "Display name of the API key.",
            "workspace_id": "ID of the workspace the key belongs to, or null for the default workspace.",
            "created_at": "RFC 3339 timestamp of when the API key was created.",
            "created_by_id": "ID of the actor that created the API key.",
            "created_by_type": "Type of the actor that created the API key.",
            "partial_key_hint": "Partially redacted hint for the API key value.",
            "status": "Key status: active, archived, expired, or inactive.",
        },
    },
    "workspace_members": {
        "description": "Membership rows mapping users to the workspaces they belong to, one row per (workspace, user).",
        "docs_url": f"{_ADMIN_API_DOCS}/workspace_members/list-workspace-members",
        "columns": {
            "type": 'Object type, always "workspace_member".',
            "user_id": "ID of the member user.",
            "workspace_id": "ID of the workspace the user is a member of.",
            "workspace_role": "Role within the workspace (workspace_admin, workspace_developer, ...).",
        },
    },
    "usage_report": {
        "description": "Claude Messages API token usage aggregated into daily buckets, broken down by model, workspace, API key, service tier, context window, and inference geo.",
        "docs_url": f"{_ADMIN_API_DOCS}/usage-cost/get-messages-usage-report",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the bucket start and every grouping dimension.",
            "starting_at": "Start of the time bucket (inclusive) in RFC 3339 format.",
            "ending_at": "End of the time bucket (exclusive) in RFC 3339 format.",
            "account_id": "ID of the user account that made the requests, or null.",
            "api_key_id": "ID of the API key used, or null.",
            "service_account_id": "ID of the service account that made the requests, or null.",
            "workspace_id": "ID of the workspace, or null for the default workspace.",
            "model": "Model used, or null.",
            "service_tier": "Service tier used (standard, batch, priority, ...), or null.",
            "context_window": "Context window bucket used (0-200k or 200k-1M), or null.",
            "inference_geo": "Inference geo used (global, us, not_available), or null.",
            "uncached_input_tokens": "Number of uncached input tokens processed.",
            "cache_read_input_tokens": "Number of input tokens read from the cache.",
            "cache_creation_ephemeral_1h_input_tokens": "Input tokens used to create the 1-hour cache entry.",
            "cache_creation_ephemeral_5m_input_tokens": "Input tokens used to create the 5-minute cache entry.",
            "output_tokens": "Number of output tokens generated.",
            "web_search_requests": "Number of server-side web search requests made.",
        },
    },
    "cost_report": {
        "description": "Daily cost in USD for your Anthropic organization, broken down by workspace and cost description.",
        "docs_url": f"{_ADMIN_API_DOCS}/usage-cost/get-cost-report",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the bucket start and every grouping dimension.",
            "starting_at": "Start of the time bucket (inclusive) in RFC 3339 format.",
            "ending_at": "End of the time bucket (exclusive) in RFC 3339 format.",
            "workspace_id": "ID of the workspace the cost is associated with, or null for the default workspace.",
            "description": "Human-readable description of the cost item.",
            "cost_type": "Type of cost: tokens, web_search, code_execution, or session_usage.",
            "model": "Model the cost is attributed to, or null for non-token costs.",
            "service_tier": "Service tier the cost is attributed to (standard or batch), or null.",
            "token_type": "Token type the cost is attributed to (e.g. output_tokens), or null.",
            "context_window": "Input context window the cost is attributed to, or null.",
            "inference_geo": "Data-residency region the cost is attributed to (global, us, not_available), or null.",
            "currency": 'Currency code for the amount, currently always "USD".',
            "amount": 'Cost amount in the lowest currency unit (cents) as a decimal string, e.g. "123.45".',
        },
    },
    "claude_code_analytics": {
        "description": "Claude Code productivity metrics, one row per user per day: sessions, lines of code, commits, pull requests, and tool-action accept/reject counts.",
        "docs_url": f"{_ADMIN_API_DOCS}/usage-cost/get-claude-code-analytics",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the day and every actor/terminal dimension.",
            "date": "UTC day the metrics are aggregated over, in RFC 3339 format.",
            "organization_id": "ID of the organization the activity belongs to.",
            "actor_type": "Type of actor: user_actor (a person) or api_actor (an API key).",
            "actor_email_address": "Email address of the user actor, or null for API actors.",
            "actor_api_key_name": "Name of the API key for an API actor, or null for user actors.",
            "customer_type": "Billing relationship: api (pay-as-you-go) or subscription (Pro/Team).",
            "terminal_type": "Terminal the sessions ran in (e.g. vscode, iTerm.app, tmux).",
            "num_sessions": "Number of Claude Code sessions that day.",
            "lines_of_code_added": "Lines of code added by Claude Code.",
            "lines_of_code_removed": "Lines of code removed by Claude Code.",
            "commits_by_claude_code": "Number of git commits created by Claude Code.",
            "pull_requests_by_claude_code": "Number of pull requests created by Claude Code.",
            "edit_tool_accepted": "Edit tool actions the user accepted.",
            "edit_tool_rejected": "Edit tool actions the user rejected.",
            "multi_edit_tool_accepted": "Multi-edit tool actions the user accepted.",
            "multi_edit_tool_rejected": "Multi-edit tool actions the user rejected.",
            "write_tool_accepted": "Write tool actions the user accepted.",
            "write_tool_rejected": "Write tool actions the user rejected.",
            "notebook_edit_tool_accepted": "Notebook-edit tool actions the user accepted.",
            "notebook_edit_tool_rejected": "Notebook-edit tool actions the user rejected.",
        },
    },
    "claude_code_model_breakdown": {
        "description": "Per-model token usage and estimated cost for Claude Code, one row per user per day per model.",
        "docs_url": f"{_ADMIN_API_DOCS}/usage-cost/get-claude-code-analytics",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the day, actor/terminal dimensions, and model.",
            "date": "UTC day the metrics are aggregated over, in RFC 3339 format.",
            "organization_id": "ID of the organization the activity belongs to.",
            "actor_type": "Type of actor: user_actor (a person) or api_actor (an API key).",
            "actor_email_address": "Email address of the user actor, or null for API actors.",
            "actor_api_key_name": "Name of the API key for an API actor, or null for user actors.",
            "customer_type": "Billing relationship: api (pay-as-you-go) or subscription (Pro/Team).",
            "terminal_type": "Terminal the sessions ran in (e.g. vscode, iTerm.app, tmux).",
            "model": "Model the tokens and cost are attributed to (e.g. claude-opus-4-8).",
            "input_tokens": "Uncached input tokens used against this model.",
            "output_tokens": "Output tokens generated by this model.",
            "cache_read_tokens": "Input tokens read from the prompt cache.",
            "cache_creation_tokens": "Input tokens used to create prompt-cache entries.",
            "estimated_cost_amount": "Estimated cost in the lowest currency unit (cents) as a decimal string.",
            "estimated_cost_currency": 'Currency code for the estimated cost, currently always "USD".',
        },
    },
    "analytics_user_activity": {
        "description": (
            "Per-seat engagement across Claude products, one row per organization member per UTC day. "
            "Metric columns are prefixed by the product surface they measure: chat, claude_code, "
            "cowork, design, office (per Office app) and science."
        ),
        "docs_url": f"{_ANALYTICS_API_DOCS}/users/list",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the day and the user id.",
            "date": "UTC day the metrics are aggregated over, in RFC 3339 format.",
            "user_id": "Tagged identifier of the organization member the activity belongs to.",
            "user_email_address": "Email address of the organization member.",
            "last_activity_date": "Most recent UTC day the member had any counted activity, or null if that reporting is off for the organization.",
            "web_search_count": "Web searches the member performed.",
            "distinct_user_count": "Distinct active members represented by the row. Null on per-member rows.",
            "rbac_group_id": "Tagged RBAC group identifier. Null unless the request grouped by group.",
            "rbac_group_name": "Display name of the RBAC group, alongside rbac_group_id when it resolves.",
            "chat_message_count": "Messages the member sent in Claude chat.",
            "chat_distinct_conversation_count": "Distinct chat conversations the member took part in.",
            "chat_thinking_message_count": "Chat messages that used extended thinking.",
            "claude_code_core_metrics_distinct_session_count": "Distinct Claude Code sessions.",
            "claude_code_core_metrics_commit_count": "Commits made through Claude Code.",
            "claude_code_core_metrics_pull_request_count": "Pull requests created through Claude Code.",
            "claude_code_core_metrics_lines_of_code_added_count": "Lines of code added through Claude Code.",
            "claude_code_core_metrics_lines_of_code_removed_count": "Lines of code removed through Claude Code.",
            "cowork_message_count": "Messages the member sent in Cowork sessions.",
            "cowork_distinct_session_count": "Distinct Cowork sessions.",
            "design_message_count": "Messages the member sent in Claude Design sessions.",
            "science_message_count": "Messages the member sent in Claude Science sessions.",
        },
    },
    "analytics_user_cost": {
        "description": (
            "Cost attributed to a seat user, one row per member per UTC day. Covers only cost that "
            "belongs to a seat user; org-wide totals including direct API-key traffic are in cost_report."
        ),
        "docs_url": f"{_ANALYTICS_API_DOCS}/cost/list_by_user",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the day and the user id.",
            "starting_at": "Start of the day the cost is bucketed into, in RFC 3339 format.",
            "ending_at": "End of the bucket (exclusive), in RFC 3339 format.",
            "user_id": "Tagged identifier of the member the cost is attributed to.",
            "user_email": "Email address of the member, or null once the account is deleted.",
            "user_name": "Full name of the member, or null if unset or hidden for a removed member.",
            "user_deleted": "True when the account is deleted or the member has left the organization.",
            "amount": "Post-discount, pre-credit cost in fractional cents, as a decimal string. Divide by 100 for dollars.",
            "list_amount": "List-price (pre-discount) cost in fractional cents, as a decimal string.",
            "currency": 'Currency code for the cost amounts, currently always "USD".',
            "requests": "API requests in the row's scope. Counts execution spans for code execution.",
        },
    },
    "analytics_user_usage": {
        "description": (
            "Token usage attributed to a seat user, one row per member per UTC day. Covers only usage "
            "that belongs to a seat user; org-wide totals including direct API-key traffic are in usage_report."
        ),
        "docs_url": f"{_ANALYTICS_API_DOCS}/usage/list_by_user",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the day and the user id.",
            "starting_at": "Start of the day the usage is bucketed into, in RFC 3339 format.",
            "ending_at": "End of the bucket (exclusive), in RFC 3339 format.",
            "user_id": "Tagged identifier of the member the usage is attributed to.",
            "user_email": "Email address of the member, or null once the account is deleted.",
            "user_name": "Full name of the member, or null if unset or hidden for a removed member.",
            "user_deleted": "True when the account is deleted or the member has left the organization.",
            "uncached_input_tokens": "Input tokens processed without a cache hit.",
            "cache_read_input_tokens": "Input tokens read from the prompt cache.",
            "cache_creation_ephemeral_1h_input_tokens": "Input tokens used to create 1-hour prompt-cache entries.",
            "cache_creation_ephemeral_5m_input_tokens": "Input tokens used to create 5-minute prompt-cache entries.",
            "output_tokens": "Output tokens generated.",
            "total_tokens": "Total tokens across every token type.",
            "requests": "API requests in the row's scope. Counts execution spans for code execution.",
            "web_search_requests": "Web search requests made through server-side tool use.",
        },
    },
    "rbac_groups": {
        "description": (
            "Groups in your Claude Enterprise organization, the join between members and the custom "
            "roles that grant their permissions. Groups are owned by the enterprise as a whole, so "
            "this table spans every linked organization."
        ),
        "docs_url": f"{_USER_MANAGEMENT_API_DOCS}/rbac_groups/list",
        "columns": {
            "id": "Unique identifier for the group, prefixed rbac_group_.",
            "type": 'Object type, always "rbac_group".',
            "name": "Display name of the group. Anthropic does not enforce uniqueness.",
            "roles": "IDs of the custom roles attached to the group. Null when role data was temporarily unavailable, rather than empty.",
            "source_type": 'How the group was created: "direct" in claude.ai, or "scim" by your identity provider.',
            "created_at": "RFC 3339 timestamp of when the group was created.",
            "updated_at": "RFC 3339 timestamp of when the group was last updated.",
        },
    },
    "rbac_group_members": {
        "description": (
            "Membership rows mapping users to the Claude Enterprise groups they hold, one row per "
            "(group, user). Joins to users on user_id and to rbac_groups on group_id."
        ),
        "docs_url": f"{_USER_MANAGEMENT_API_DOCS}/rbac_groups/members/list",
        "columns": {
            "type": 'Object type, always "rbac_group_member".',
            "group_id": "ID of the group the user holds.",
            "user_id": "ID of the member user.",
            "email": "Email address of the member user.",
            "created_at": "RFC 3339 timestamp of when the user was added to the group.",
        },
    },
    "rbac_roles": {
        "description": (
            "Custom roles defined in your Claude Enterprise organization, the lookup resolving the "
            "role IDs carried on rbac_groups. The role catalog is per-organization while groups span "
            "the enterprise, so a group can name a role this table does not contain."
        ),
        "docs_url": f"{_USER_MANAGEMENT_API_DOCS}/rbac_roles/list",
        "columns": {
            "id": "Unique identifier for the custom role, prefixed rbac_role_.",
            "type": 'Object type, always "rbac_role".',
            "name": "Display name of the custom role.",
            "created_at": "RFC 3339 timestamp of when the role was created.",
            "updated_at": "RFC 3339 timestamp of when the role was last updated.",
        },
    },
    "rbac_role_permissions": {
        "description": (
            "What each custom role grants, one row per (role, action, resource). Anthropic omits rows "
            "for features your organization has not enabled. A capability_access_all or "
            "capability_access_all_ga action is a blanket grant listed as a single row, so a tally of "
            "a role's access has to treat it as covering every product feature it describes rather "
            "than only the features named in other rows."
        ),
        "docs_url": f"{_USER_MANAGEMENT_API_DOCS}/rbac_roles/permissions/list",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the role plus the action and resource the row grants.",
            "role_id": "ID of the custom role the permission belongs to.",
            "action": "What the permission grants on the resource: a product-feature or admin-panel entitlement on an organization resource, a tool-access action (use, always_allow) on a connector, an authentication-method action (interactive, managed), or grant on a connector OAuth scope.",
            "resource_type": "What the permission applies to: organization, connector, all_connectors, connector_tool, or connector_scope.",
            "organization_id": "UUID of the organization, on an organization resource. Null otherwise.",
            "connector_id": "ID of the connector, on a connector, connector_tool or connector_scope resource. Null otherwise.",
            "tool_name": "Published name of the connector tool, on a connector_tool resource. Server-encoded to a prefix plus hash when the published name holds characters outside [a-zA-Z0-9_-].",
            "scope": "OAuth scope the role may receive when tokens are minted for the connector, on a connector_scope resource. Usually server-encoded, because OAuth scopes commonly contain : and /.",
        },
    },
    "analytics_connector_usage": {
        "description": (
            "Connector adoption, one row per connector per UTC day. Connector names are normalized "
            'across their sources, so "Atlassian MCP server" and "mcp-atlassian" both appear as '
            '"atlassian". Metric columns are prefixed by the product surface they measure: chat, '
            "claude_code, cowork and office (per Office app)."
        ),
        "docs_url": f"{_ANALYTICS_API_DOCS}/connectors/list",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the day and the connector name.",
            "date": "UTC day the metrics are aggregated over, in RFC 3339 format.",
            "connector_name": "Normalized name of the connector, and the row's stable key. Holds an opaque connector ID on some rows.",
            "connector_display_name": "Readable name for rows whose connector_name is an opaque ID. Null when connector_name is already readable or the ID no longer resolves. Not unique.",
            "distinct_user_count": "Distinct users who used the connector that day.",
            "individual_auth_distinct_user_count": "Distinct users whose use of the connector ran on their own credential, connected through their own consent flow.",
            "managed_auth_distinct_user_count": "Distinct users whose use of the connector ran on an organization-managed credential provisioned through your identity provider. Null, never 0, when managed-auth reporting is off or the day predates 2026-07-01.",
            "read_call_count": "Connector tool calls whose read-only annotation marked them read-only. Null, never 0, when the read/write split is off for your organization or the day predates 2026-05-29.",
            "write_call_count": "Connector tool calls whose read-only annotation marked them not read-only.",
            "unclassified_call_count": "Connector tool calls with no trusted read-only annotation. The annotation is optional in the MCP spec, so this bucket is commonly large.",
            "chat_distinct_conversation_connector_used_count": "Distinct Claude chat conversations the connector was used in.",
            "claude_code_distinct_session_connector_used_count": "Distinct Claude Code sessions the connector was used in.",
            "cowork_distinct_session_connector_used_count": "Distinct Cowork sessions the connector was used in.",
            "office_excel_distinct_session_connector_used_count": "Distinct Claude in Excel sessions the connector was used in.",
            "office_outlook_distinct_session_connector_used_count": "Distinct Claude in Outlook sessions the connector was used in.",
            "office_powerpoint_distinct_session_connector_used_count": "Distinct Claude in PowerPoint sessions the connector was used in.",
            "office_word_distinct_session_connector_used_count": "Distinct Claude in Word sessions the connector was used in.",
        },
    },
    "analytics_plugin_usage": {
        "description": (
            "Plugin installs and invocations across Cowork and Claude Code, one row per plugin per "
            'UTC day. The plugin_name value "third-party" is an aggregate bucket rather than a '
            "plugin: it collects activity the reporting client sent no plugin name for."
        ),
        "docs_url": f"{_ANALYTICS_API_DOCS}/plugins/list",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the day and the plugin name.",
            "date": "UTC day the metrics are aggregated over, in RFC 3339 format.",
            "plugin_name": "Name of the plugin, and the row's stable key.",
            "plugin_id": "Stable plugin identifier (for example serena@claude-plugins-official). Null for third-party Claude Code plugins and for Cowork slash commands that carry only a hashed ID.",
            "distinct_user_count": "Distinct users with install or invocation activity for the plugin that day. Install-only users count.",
            "install_count": "Distinct users who installed the plugin that day.",
            "invocation_count": "Plugin invocations that day.",
            "claude_code_distinct_session_plugin_used_count": "Distinct Claude Code sessions the plugin was invoked in.",
            "cowork_distinct_session_plugin_used_count": "Distinct Cowork sessions the plugin was invoked in.",
        },
    },
    "analytics_skill_usage": {
        "description": (
            "Skill adoption and the spend attributed to each skill, one row per skill per UTC day. A "
            "skill counts as used only when it is explicitly activated, so a skill that is merely "
            "installed, listed, or read as a plain file is not counted. Metric columns are prefixed "
            "by the product surface they measure: chat, claude_code, cowork and office (per Office app)."
        ),
        "docs_url": f"{_ANALYTICS_API_DOCS}/skills/list",
        "columns": {
            "id": "Synthesized surrogate key: a hash of the day and the skill name.",
            "date": "UTC day the metrics are aggregated over, in RFC 3339 format.",
            "skill_name": "Name of the skill, and the row's stable key. Holds an opaque skill ID for user and organization skill types and plugin-delivered skills.",
            "skill_display_name": "Readable name for rows whose skill_name is an opaque ID. Null for private user-defined skills, whose names are not disclosed to analytics keys.",
            "share_status": "Share status on claude.ai: private, organization, or public. Null for skills used only in Claude Code or Office.",
            "distinct_user_count": "Distinct users who activated the skill that day.",
            "invocation_count": "Times the skill was activated that day. Null when invocation reporting is off for your organization.",
            "enable_count": "Distinct accounts that enabled the skill that day, on claude.ai only. Null when enable reporting is off for your organization.",
            "estimated_overage_spend": "Estimated post-discount, pre-credit overage spend attributed to the skill, in fractional cents as a decimal string. An estimate of the cost of the requests the skill took part in, not the skill's incremental cost. Usage covered by seat allowances allocates 0.",
            "attributed_list_price": "List-price value of the member requests attributed to the skill, in fractional cents as a decimal string. Counts seat-covered usage too, so it does not tie to billed spend. Null on chat rows, which carry no request-level attribution.",
            "currency": 'Currency code for the monetary columns, always "USD" when either is populated and null when both are null.',
            "chat_distinct_conversation_skill_used_count": "Distinct Claude chat conversations the skill was activated in.",
            "claude_code_distinct_session_skill_used_count": "Distinct Claude Code sessions the skill was activated in.",
            "cowork_distinct_session_skill_used_count": "Distinct Cowork sessions the skill was activated in.",
            "office_excel_distinct_session_skill_used_count": "Distinct Claude in Excel sessions the skill was activated in.",
            "office_outlook_distinct_session_skill_used_count": "Distinct Claude in Outlook sessions the skill was activated in.",
            "office_powerpoint_distinct_session_skill_used_count": "Distinct Claude in PowerPoint sessions the skill was activated in.",
            "office_word_distinct_session_skill_used_count": "Distinct Claude in Word sessions the skill was activated in.",
        },
    },
    "analytics_summaries": {
        "description": (
            "Organization-wide activity and adoption as Anthropic rolls it up, one row per UTC day. "
            "Active-user counts come in three windows: the day itself, and the 7- and 30-day rolling "
            "windows ending on it. Per-product columns are omitted while the per-product breakdown is "
            "not enabled for your organization."
        ),
        "docs_url": f"{_ANALYTICS_API_DOCS}/retrieve_summaries",
        "columns": {
            "starting_at": "Start of the day the row covers, UTC midnight in RFC 3339 format.",
            "ending_at": "End of the day the row covers (exclusive), UTC midnight in RFC 3339 format.",
            "assigned_seat_count": "Seats assigned to members at the time of the daily snapshot.",
            "pending_invite_count": "Invitations to join the organization still pending.",
            "daily_active_user_count": "Members with token consumption on the day.",
            "weekly_active_user_count": "Members with token consumption in the 7-day rolling window.",
            "monthly_active_user_count": "Members with token consumption in the 30-day rolling window.",
            "daily_adoption_rate": "Percentage of assigned seats active on the day (DAU / assigned_seat_count * 100).",
            "weekly_adoption_rate": "Percentage of assigned seats active in the 7-day rolling window.",
            "monthly_adoption_rate": "Percentage of assigned seats active in the 30-day rolling window.",
            "chat_daily_active_user_count": "Members with claude.ai chat activity on the day.",
            "chat_weekly_active_user_count": "Members with claude.ai chat activity in the 7-day rolling window.",
            "chat_monthly_active_user_count": "Members with claude.ai chat activity in the 30-day rolling window.",
            "claude_code_daily_active_user_count": "Members with Claude Code activity on the day.",
            "claude_code_weekly_active_user_count": "Members with Claude Code activity in the 7-day rolling window.",
            "claude_code_monthly_active_user_count": "Members with Claude Code activity in the 30-day rolling window.",
            "cowork_daily_active_user_count": "Members with Cowork activity on the day.",
            "cowork_weekly_active_user_count": "Members with Cowork activity in the 7-day rolling window.",
            "cowork_monthly_active_user_count": "Members with Cowork activity in the 30-day rolling window.",
            "claude_design_daily_active_user_count": "Members with Claude Design activity on the day.",
            "claude_design_weekly_active_user_count": "Members with Claude Design activity in the 7-day rolling window.",
            "claude_design_monthly_active_user_count": "Members with Claude Design activity in the 30-day rolling window.",
            "office_agent_daily_active_user_count": "Members with Claude in Office activity on the day.",
            "office_agent_weekly_active_user_count": "Members with Claude in Office activity in the 7-day rolling window.",
            "office_agent_monthly_active_user_count": "Members with Claude in Office activity in the 30-day rolling window.",
            "science_daily_active_user_count": "Members with Claude Science activity on the day.",
            "science_weekly_active_user_count": "Members with Claude Science activity in the 7-day rolling window.",
            "science_monthly_active_user_count": "Members with Claude Science activity in the 30-day rolling window.",
            "science_entitled_user_count": "Members holding a Claude Science seat entitlement at the time of the daily snapshot, independent of the organization-level Claude Science toggle.",
        },
    },
}
