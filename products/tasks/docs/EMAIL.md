# Starting a task by email

A project can have a task inbox address. A member of the project's organization emails it, and PostHog AI starts a task for them, in the same shape as a task started from a PostHog AI conversation: no repository, full MCP scopes, filed in the sender's personal `#me` channel. The sender gets one acknowledgement email in the same thread with a link to the task.

## Enabling it

The address lives on `TeamTasksConfig.email_inbound_token` and is exposed through the team config API:

| Call                                                 | Effect                                                      |
| ---------------------------------------------------- | ----------------------------------------------------------- |
| `GET /api/projects/:id/tasks/config/`                | `email_inbox_address` is the address, or null when disabled |
| `POST /api/projects/:id/tasks/config/email_inbox/`   | Enable, or rotate an existing address. Admin only           |
| `DELETE /api/projects/:id/tasks/config/email_inbox/` | Disable. Mail to the old address is dropped. Admin only     |

The address is `code-<32 hex chars>@<CONVERSATIONS_EMAIL_INBOUND_DOMAIN>`. The token is the only secret, so treat the address like a webhook URL and rotate it if it leaks. Enabling fails with a 400 on an instance where that domain setting is empty.

## How mail gets in

Mail arrives through the conversations product's Mailgun webhook (`/api/conversations/v1/email/inbound`), which already handles support tickets at `team-<token>@…` addresses. The webhook checks the recipient for the `code-` prefix first and hands the parsed message to `products.tasks.backend.facade.email_intake.start_task_from_email`. Everything after that lives in `products/tasks/backend/logic/services/email_intake.py`.

Region routing is the same as for support mail: the primary region proxies a message whose token it does not know to the secondary region.

## Who may start a task

The bar is the same as the Slack entrypoint: the sender must be a member of the project's organization, matched on email address. On top of that the webhook must have authenticated the sender (SPF pass, or DKIM aligned with the From domain), which the conversations product already computes. An unauthenticated or unknown sender gets no task and no reply, so the address does not act as an oracle for membership.

## What one email becomes

- Title: the subject, or the first line of the body when there is no subject.
- Description: the stripped reply text (quoted history removed), or the subject when the body is empty.
- An email with neither is dropped.
- `Task.origin_product` is `email`, `Task.origin_key` is `email:<Message-ID>`. The unique index on `origin_key` makes Mailgun retries idempotent.
- AI credits quota is checked before creation, like the PostHog AI entrypoint.

Replies to the acknowledgement are not read back into the task yet. A follow-up needs a message-id mapping for tasks, like `EmailMessageMapping` does for tickets.

## Replying to a PostHog email

Once a project has an inbox address, the materialized view failure emails (the per-failure email and the daily digest) carry it as `Reply-To`. A member replies with what they want done, and the reply starts a task the same way a fresh email does.

- The `Re:` prefix is dropped from the title, so the task is named after the failing view.
- The reply's own text is the description. The quoted email underneath it is appended as "The sender replied to this email", so the agent sees the failure report the person is pointing at.
- Automatic replies (out-of-office and similar, detected by `Auto-Submitted`, `X-Auto-Response-Suppress`, and `Precedence`) create nothing. The acknowledgement email sets `Auto-Submitted: auto-replied` so it does not trigger anyone else's autoresponder.

Without an inbox address the failure emails keep the instance default `Reply-To`. Other PostHog notification emails do not set the inbox address yet; each sender opts in by passing `reply_to` to `EmailMessage`.
