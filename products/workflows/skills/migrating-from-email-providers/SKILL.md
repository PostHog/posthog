---
name: migrating-from-email-providers
description: 'Move a team from an email API provider such as Resend to PostHog: read the small data (topics, templates, automations, segments, domains) through the provider''s MCP when it''s connected, let PostHog fetch the bulk lists (suppressions, unsubscribes) with a key, then walk through DNS, template review and switching the code. Use when asked to migrate, move, switch, copy or import from Resend to PostHog, "switch to PostHog", or to bring suppressions, unsubscribes or email templates from another provider. For Customer.io automations use migrating-from-customer-io.'
---

# Moving from another email provider

One flow: confirm the project, read what's small yourself, let PostHog fetch what's large, then help the team switch. Every part of it lands in one import run, which shows in the project's import history and in the app.

Call `provider-imports-providers` first. It lists the tools this project can import from and each one's `steps`. A step with `passed_objects` can import from objects you read through the provider's MCP. A step without them, such as suppressions or unsubscribes, is always fetched by PostHog with an API key. If the provider isn't listed, the import isn't turned on for this project, so stop and say so.

## Why the split

Automations, templates, topics, segments and domains are a few dozen objects, so reading them through the provider's MCP costs little and needs no key. Suppression and contact lists can run to thousands of rows. Copying them through you would spend the user's tokens on every row, so PostHog pages through them itself in the background.

## What moves

| Data                     | How it's read         | In PostHog                        | What the team does                                  |
| ------------------------ | --------------------- | --------------------------------- | --------------------------------------------------- |
| Topics                   | Provider MCP, or key  | Marketing categories              | Checks topics that only send to people who opted in |
| Templates                | Provider MCP, or key  | Library templates, keyed by alias | Fixes what the notes mention, then sends a test     |
| Automations and segments | Provider MCP, or key  | Draft workflows, static cohorts   | Sends trigger events to PostHog, reviews, enables   |
| Domains                  | Provider MCP, or key  | A list only                       | Adds each domain and publishes new DNS records      |
| Suppression list         | PostHog, with the key | Suppression list                  | Reads the summary                                   |
| Unsubscribed contacts    | PostHog, with the key | Opted out of all marketing email  | Nothing                                             |
| Topic choices            | PostHog, with the key | Category opt-outs                 | Nothing                                             |

API keys, webhooks, send history and stats stay with the old provider. Contacts never become people. Importing people has a separate list upload, and it creates billable events, so only mention it if the user asks.

## Steps

1. **Confirm the project.** Read it with `project-get`, tell the user its name and id, and ask whether the data belongs there. If not, switch with `switch-project`.
2. **Check for a running import.** `provider-imports-list`. A new start while one is active returns 409, so report on that run instead.
3. **Choose the steps.** Take them all unless the user says otherwise. Automations also need `cohort:write` on a PostHog key with limited scopes. On a refusal that names it, drop `automations` or ask the user for that scope.
4. **Read the small data.** When the provider's MCP is connected, read every kind the selected steps list under `passed_objects`. See the provider notes below for which calls to make. Copy each value as the MCP shows it into the field names `provider-imports-create` describes. Never read or pass contacts, suppressed addresses or people. Without the provider's MCP, skip this: PostHog reads these steps with the key too.
5. **Summarize before importing.** Tell the user what you read: how many topics, templates, automations, segments and domains, and the provider's `not_imported` text. Ask before going on.
6. **Get a key** for the steps PostHog fetches. When the provider's MCP can create keys, create a temporary one yourself, so the user never handles it. Don't show, log or store it. When it can't, ask the user to create one and put it where you can read it without it passing through the chat, such as a line in a `.env` file you read in a shell command, or to start the import themselves in the app under Workflows, Opt-outs, Import from another tool. If every selected step imports from objects, no key is needed.
7. **Start.** `provider-imports-create` with `provider`, `steps`, `objects` and `api_key`. Steps imported from `objects` have finished when it returns.
8. **Follow it.** Poll `provider-imports-get` every minute or so until `status` is `completed` or `failed`. A `running` step with a `last_error` is retrying by itself, so don't start again. Report each step's `counts`.
9. **Delete a temporary key** once the run has ended, with the provider's MCP. Delete only the key you created, by its id. If a step failed and the user wants to import again, keep the key until that import ends, since a new import continues a failed step only with the same key.
10. **Report the notes.** Go through `items` with the user: each template and workflow with its link and notes. A link is a path in the PostHog app, so put the project's PostHog URL in front of it. Say plainly how many spam complaints imported, because PostHog still sends them transactional email while Resend doesn't.
11. **Walk through the switch.** See below.

## Provider notes

**Resend.** The Resend MCP (https://mcp.resend.com/mcp) answers in text, so copy each field by name.

- `topics`: `list-topics`, as `{id, name, description, default_subscription, visibility}`.
- `segments`: `list-segments`, as `{id, name}`.
- `templates`: `list-templates`, then `get-template` with each id, as `{id, name, alias, status, subject, from, reply_to, variables: [{key, type, fallback_value}], html, text}`. Use null where it shows none.
- `automations`: `get-automation` without an id lists them; then call it with each id and pass `{id, name, status, workflow}`, with the `workflow` JSON exactly as it comes back.
- `domains`: `list-domains`, then `get-domain` with each id, as `{id, name, status, records: [{record, type, name, value, ttl, status, priority}]}`.
- Page any list with `after` until it says nothing more is available.
- Key: `create-api-key` with `permission: full_access` and a name such as "PostHog import (temporary)", then `remove-api-key` with its id once the run ends. Resend has no read-only keys. `topic_opt_outs` reads contacts one at a time, about 7,000 an hour, so a very large list can take a day. A run stops after 24 hours.

**Customer.io.** Automations go through `workflows-import-customerio` instead; see `migrating-from-customer-io`. `provider-imports-create` imports Customer.io suppressions and unsubscribes with an App API key.

## Importing again never undoes a change

An address someone removed from the suppression list, a person opted back in, an edited or deleted category, and an edited or deleted template all stay as they are. So a template or automation imported before does not pick up changes from the provider. To re-import one, change its alias in Resend, or copy the change by hand.

## The switch

1. **Domains.** PostHog signs mail with its own keys, so a domain needs new records even if it already sends through Resend. Add each domain under Workflows, Channels and publish the records. Keep the Resend records, because both tools can sign for one domain. A note in `items` says when Resend already uses PostHog's default `feedback` subdomain: choose another MAIL FROM subdomain there, because two services can't share one MX record.
2. **Templates.** Fix what the notes mention. Resend fills `FIRST_NAME` and other contact fields itself, and PostHog doesn't, so the app must pass them. Send a test to the user's own address.
3. **Code.** Use the `sending-transactional-emails` skill and its moving-from-other-providers reference. The template key is the Resend alias, or `resend-<id>` when it has none. Move one low-risk email first. Map errors too: PostHog refuses a send to a hard-bounced address with `recipient_suppressed`, and that must not go back into a retry loop.
4. **Automations.** Each draft notes which events the app has to send to PostHog as well. Use the `building-workflows` skill to test and enable. Turn the automation off in Resend at the same moment, or people get both emails. Never enable a draft without the user's sign-off.
5. **Volume.** Mailbox providers slow down a sudden jump, so move high volume over several days. Check the project's allowance with `workflows-reputation-get` first, because new projects start with a low limit on marketing email.
6. **Clean up.** Once nothing sends through Resend, the user removes its DNS records.
