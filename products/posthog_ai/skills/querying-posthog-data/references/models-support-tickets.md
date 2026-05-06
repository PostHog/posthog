# Support Tickets

## Ticket (`system.support_tickets`)

Support tickets from the conversations product, created via widget, email, or Slack channels.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key
`team_id` | integer | NOT NULL | Team this ticket belongs to
`ticket_number` | integer | NOT NULL | Auto-incrementing number, unique per team
`channel_source` | varchar(20) | NOT NULL | Origin channel: `widget`, `email`, or `slack`
`channel_detail` | varchar(30) | NULL | Sub-type: `slack_channel_message`, `slack_bot_mention`, `slack_emoji_reaction`, `widget_embedded`, `widget_api`
`distinct_id` | varchar(400) | NOT NULL | PostHog distinct_id linking the ticket to a person
`status` | varchar(20) | NOT NULL | `new`, `open`, `pending`, `on_hold`, or `resolved`
`priority` | varchar(20) | NULL | `low`, `medium`, or `high`
`anonymous_traits` | jsonb | NOT NULL | Customer-provided traits (name, email, etc.)
`message_count` | integer | NOT NULL | Total number of messages in the ticket
`unread_customer_count` | integer | NOT NULL | Messages the customer hasn't seen (from team/AI)
`unread_team_count` | integer | NOT NULL | Messages the team hasn't seen (from customer)
`last_message_at` | timestamp with tz | NULL | When the most recent message was sent
`last_message_text` | varchar(500) | NULL | Truncated preview of the most recent message
`email_subject` | varchar(500) | NULL | Email subject line (email-originated tickets only)
`email_from` | varchar(254) | NULL | Sender email address (email-originated tickets only)
`session_id` | varchar(64) | NULL | PostHog session ID captured at ticket creation
`session_context` | jsonb | NOT NULL | Session context data (replay URL, current URL, etc.)
`sla_due_at` | timestamp with tz | NULL | SLA deadline set via workflows, null means no SLA
`created_at` | timestamp with tz | NOT NULL | When the ticket was created
`updated_at` | timestamp with tz | NOT NULL | When the ticket was last updated

### Key Relationships

- Tickets belong to a **Team** (`team_id`)
- Tickets are linked to a **Person** via `distinct_id`
- Ticket assignments are managed via `TicketAssignment` (not exposed as a system table)

### Important Notes

- The `status` field follows a lifecycle: `new` -> `open` -> `pending`/`on_hold` -> `resolved`
- The `anonymous_traits` field contains customer-provided key-value pairs, commonly including `name` and `email`
- The `session_context` field may contain `session_replay_url`, `current_url`, and other session metadata
- Tickets are never deleted; filter by `status` to exclude resolved tickets
