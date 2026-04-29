# Integrations

## Integration (`system.integrations`)

Third-party service connections configured per project.
Each integration represents a connection to an external service like Slack, GitHub, Salesforce, or an ad platform.

### Columns

| Column           | Type              | Nullable | Description                                                                         |
| ---------------- | ----------------- | -------- | ----------------------------------------------------------------------------------- |
| `id`             | integer           | NOT NULL | Primary key (auto-generated)                                                        |
| `team_id`        | integer           | NOT NULL | Team this integration belongs to                                                    |
| `kind`           | varchar(32)       | NOT NULL | Integration type identifier (see below)                                             |
| `integration_id` | text              | NULL     | Identifier in the external system (e.g. Slack workspace ID, GitHub installation ID) |
| `config`         | jsonb             | NOT NULL | Non-sensitive, kind-specific configuration                                          |
| `errors`         | text              | NOT NULL | Error message if the integration has issues, empty string otherwise                 |
| `created_at`     | timestamp with tz | NOT NULL | Creation timestamp                                                                  |
| `created_by_id`  | integer           | NULL     | Creator user ID                                                                     |

### Integration Kinds

`slack`, `slack-posthog-code`, `salesforce`, `hubspot`, `google-pubsub`, `google-cloud-storage`, `google-ads`, `google-sheets`, `google-cloud-service-account`, `snapchat`, `linkedin-ads`, `reddit-ads`, `tiktok-ads`, `bing-ads`, `intercom`, `email`, `linear`, `github`, `gitlab`, `meta-ads`, `twilio`, `clickup`, `vercel`, `databricks`, `azure-blob`, `firebase`, `jira`, `pinterest-ads`

### Key Relationships

- Integrations belong to a **Team** (`team_id`)
- Integrations are referenced by **Hog functions**, **Batch exports** and **Workflows** that use external services

### Important Notes

- `sensitive_config` (encrypted credentials, tokens) is deliberately not exposed in this table
- `config` structure varies by integration kind and may include account names, workspace IDs, or other non-secret metadata
- Each (`team_id`, `kind`, `integration_id`) combination is unique
- Most integrations are created via OAuth flows or file uploads, not direct API calls
