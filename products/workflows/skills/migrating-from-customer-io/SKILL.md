---
name: migrating-from-customer-io
description: 'Move Customer.io automations into PostHog as draft workflows. Read each automation with the Customer.io MCP or CLI, preview the import with workflows-import-customerio (dry_run), then import and walk the user through what needs their input. Use when asked to migrate, move, switch, copy or import from Customer.io (customer.io, CIO) to PostHog workflows, including "migrate everything to PostHog".'
---

# Migrating from Customer.io

PostHog imports Customer.io automations as **draft workflows**. Drafts never send. A person reviews each one, fixes what the import could not carry over, and enables it.

You move the data between two MCP servers. Read from Customer.io's MCP (or the `cio` CLI), and pass what it returns **unchanged** to PostHog's `workflows-import-customerio`. PostHog does the translation, so do not rebuild workflows yourself with `workflows-create`.

## Never move people

Pass automations, templates, sender identities and segment names only. Never fetch or pass customer profiles, segment members, deliveries or event data. The people are usually in PostHog already, and copying them is a privacy risk the user did not ask for.

## Keep message content out of your context

Email templates are large, often tens of kilobytes of HTML each. When the PostHog project stored a Customer.io App API key (teams that ran the opt-out import have one), PostHog reads the message content from Customer.io itself. So pass the automation graph first, and read templates only if PostHog asks for them.

## Steps

1. **Confirm the PostHog project.** The drafts go into the PostHog MCP's active project. Read it with `project-get`, tell the user its name and id, and ask whether the drafts should go there. If not, switch with `switch-project` before you read anything from Customer.io.
2. **Find the environment.** Ask which Customer.io workspace to migrate if there is more than one. Its id is the `environment_id` in every path below.
3. **List the automations.** `GET /v1/environments/{environment_id}/campaigns` with the Customer.io read tool (`cio_read_api` on the MCP, `cio api` on the CLI). It returns 20 per page through `page` (0-based): read every page until one returns fewer than 20. Show the user the list with each automation's state, and ask which to move. Running automations are the usual answer; skip archived ones unless asked.
4. **Read each automation.** `GET /v1/environments/{environment_id}/campaigns/{campaign_id}`. Keep the response's `campaign` object and its **top-level** `actions` array. `campaign.actions` does not exist.
5. **Read senders and segments.** `GET /v1/environments/{environment_id}/identities?type=email` for `sender_identities` (`id`, `email`, `name`), and the segment list for `segments` (`id`, `name`, `type` only). PostHog matches each email to the PostHog sender with the same address, and names the segments in its notes.
6. **Preview without templates.** Call `workflows-import-customerio` with `source: "customerio"`, `dry_run: true`, `campaigns: [{campaign, actions}]`, `sender_identities` and `segments`. Up to 50 automations per call.
7. **Read templates only if needed.** Go by each automation's notes, not by `content_fetched` alone: `true` only means PostHog read some content, and one automation can still miss its messages. For every automation whose notes say message content was not part of the import, or that PostHog could not read its messages, read the template of every action that has a `template_id` with `GET /v1/environments/{environment_id}/templates/{template_id}`, keep the `template` object, and preview again with `campaigns: [{campaign, actions, templates}]`. Read templates one at a time: listing every template in the workspace times out on large ones. Tell the user that Import from Customer.io on the Workflows Opt-outs tab stores their App API key, which skips this step next time.
8. **Collect snippets and layouts.** If a note names a Customer.io snippet, or a template body you read contains `{{ snippets.name }}`, read the workspace snippets and pass them as `snippets` (`{name: content}`). When PostHog read the content itself, it read the snippets too, and a note names any it could not find. If a note names a layout, read `GET /v1/environments/{environment_id}/layouts/{layout_id}` and pass its `body` as `layouts` (`{layout_id: body}`).
9. **Report the preview.** For each automation, give its status and its notes, grouped by level (see below). Ask before importing anything with status `failed`; its `validation_errors` say why the draft would be rejected.
10. **Import.** Call again with `dry_run: false` and the same arguments. Share each draft's link (`/workflows/{workflow_id}`) and the `needs_input` notes again, since the team must handle those before enabling.

When you are unsure of an endpoint's parameters, ask for that one endpoint's schema (`cio_schema` with `resource.method`). A whole resource's schema costs tens of thousands of tokens.

## Reading the notes

| Level          | Meaning                                                                                                 | What to tell the user                         |
| -------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| `needs_input`  | The draft needs a setting only the team can give: an email sender, a trigger cohort, a branch condition | These block enabling. List them per workflow. |
| `approximated` | The step works differently in PostHog, for example a wait capped at 30 days                             | Worth a look before enabling.                 |
| `unsupported`  | The setting has no PostHog equivalent and was left out, for example an SMS step                         | Decide whether to rebuild it another way.     |

The same notes appear in the PostHog app on the imported workflow, and `workflows-import-notes` returns them for one workflow.

## Senders and categories

An email gets the PostHog email sender with the same address as its Customer.io sender. When no PostHog sender has that address, a `needs_input` note names it, so the user can add it as a sender. An email's subscription topic becomes the PostHog message category the opt-out import made from that topic. When the topics were not imported, a note says so.

## Segments and cohorts

Customer.io segments do not import. An automation triggered by a segment imports with an empty trigger and a `needs_input` note. If the user already has a PostHog cohort that matches a segment, pass `segment_cohorts: {"<segment id>": <cohort id>}` and the import uses it for that segment's triggers and conditions. A cohort trigger needs a realtime cohort. A static segment gets its own note: workflows cannot check a static cohort, so the user rebuilds it as conditions.

## Push notifications

Push steps import as `unsupported` notes, and device tokens never move with the import. If the user sends push from Customer.io, tell them that a device reaches PostHog only when its app registers it with the PostHog SDK, or when they import their exported device tokens into a PostHog push channel. That token import is a separate step the user starts, because tokens are people data.

## Re-running

Importing an automation again replaces its draft, so you can re-run after fixing something in Customer.io. Edits the team made to that draft since are lost, so ask before you re-import. A workflow that someone already enabled, or that the user can't edit, is never changed: its result is `skipped`.

## After the import

Do not enable the drafts. Point the user at the `needs_input` notes, then hand over to the `building-workflows` skill for testing and enabling, which needs the user's explicit sign-off.
