---
name: migrating-from-customer-io
description: 'Move Customer.io automations into PostHog as draft workflows. Read each automation and its message templates with the Customer.io MCP or CLI, preview the import with workflows-import-customerio (dry_run), then import and walk the user through what needs their input. Use when asked to migrate, move, switch, copy or import from Customer.io (customer.io, CIO) to PostHog workflows, including "migrate everything to PostHog".'
---

# Migrating from Customer.io

PostHog imports Customer.io automations as **draft workflows**. Drafts never send. A person reviews each one, fixes what the import could not carry over, and enables it.

You move the data between two MCP servers. Read from Customer.io's MCP (or the `cio` CLI), and pass what it returns **unchanged** to PostHog's `workflows-import-customerio`. PostHog does the translation, so do not rebuild workflows yourself with `workflows-create`.

## Never move people

Pass automations and templates only. Never fetch or pass customer profiles, segment members, deliveries or event data. The people are usually in PostHog already, and copying them is a privacy risk the user did not ask for.

## Steps

1. **Find the environment.** Ask which Customer.io workspace to migrate if there is more than one. Its id is the `environment_id` in every path below.
2. **List the automations.** `GET /v1/environments/{environment_id}/campaigns` with the Customer.io read tool (`cio_read_api` on the MCP, `cio api` on the CLI). It returns 20 per page through `page` (0-based): read every page until one returns fewer than 20. Show the user the list with each automation's state, and ask which to move. Running automations are the usual answer; skip archived ones unless asked.
3. **Read each automation.** `GET /v1/environments/{environment_id}/campaigns/{campaign_id}`. Keep the response's `campaign` object and its **top-level** `actions` array. `campaign.actions` does not exist.
4. **Read the message templates.** For every action that has a `template_id` (emails, webhooks, attribute updates), `GET /v1/environments/{environment_id}/templates/{template_id}` and keep the `template` object. Without templates the messages import empty.
5. **Collect snippets.** If any template body contains `{% snippet "name" %}`, read the workspace snippets and pass them as `snippets` (`{name: content}`).
6. **Preview.** Call `workflows-import-customerio` with `source: "customerio"`, `dry_run: true` and `campaigns: [{campaign, actions, templates}]`. Up to 50 automations per call.
7. **Report the preview.** For each automation, give its status and its notes, grouped by level (see below). Ask before importing anything with status `failed`; its `validation_errors` say why the draft would be rejected.
8. **Import.** Call again with `dry_run: false`. Share each draft's link (`/workflows/{workflow_id}`) and the `needs_input` notes again, since the team must handle those before enabling.

## Reading the notes

| Level          | Meaning                                                                                                 | What to tell the user                         |
| -------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| `needs_input`  | The draft needs a setting only the team can give: an email sender, a trigger cohort, a branch condition | These block enabling. List them per workflow. |
| `approximated` | The step works differently in PostHog, for example a wait capped at 30 days                             | Worth a look before enabling.                 |
| `unsupported`  | The setting has no PostHog equivalent and was left out, for example an SMS step                         | Decide whether to rebuild it another way.     |

The same notes appear in the PostHog app on the imported workflow, and `workflows-import-notes` returns them for one workflow.

## Segments and cohorts

Customer.io segments do not import. An automation triggered by a segment imports with an empty trigger and a `needs_input` note. If the user already has a PostHog cohort that matches a segment, pass `segment_cohorts: {"<segment id>": <cohort id>}` and the import uses it for that segment's triggers and conditions. A cohort trigger needs a realtime cohort.

## Push notifications

Push steps import as `unsupported` notes, and device tokens never move with the import. If the user sends push from Customer.io, tell them that a device reaches PostHog only when its app registers it with the PostHog SDK, or when they import their exported device tokens into a PostHog push channel. That token import is a separate step the user starts, because tokens are people data.

## Re-running

Importing an automation again updates its draft in place, so you can re-run after fixing something in Customer.io. A workflow that someone already enabled is never changed: its result is `skipped`.

## After the import

Do not enable the drafts. Point the user at the `needs_input` notes, then hand over to the `building-workflows` skill for testing and enabling, which needs the user's explicit sign-off.
