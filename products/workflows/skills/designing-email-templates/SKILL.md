---
name: designing-email-templates
description: 'Author, save, and edit email templates in the PostHog workflows library — compose email design JSON with Liquid personalization and create and round-trip-edit templates over MCP. Use when asked to design, build, update, or fix an email template for workflows, broadcasts, or campaigns.'
---

# Designing email templates

Use this skill when creating or editing email templates for PostHog workflows — broadcast campaigns and `function_email` workflow actions send the rendered template.

## How authoring works

You author the **design JSON** (`content.email.design`) and save it with `workflows-create-email-template`. The server renders the sent email from your design with the same renderer PostHog's visual editor uses, so the template opens as editable blocks for humans and sends exactly what the design describes. Schema and a working example in [references/unlayer-design-json.md](references/unlayer-design-json.md).

When talking to the user, call it the template's **design** — the design document format is an internal implementation detail. Always share the template's `_posthogUrl` edit link in your reply after creating or updating, so the user can open it in PostHog directly.

Read [references/design-guidelines.md](references/design-guidelines.md) before composing — it covers committing to a design direction, typography, color, and the patterns that make an email look designed rather than generated. For one fragment the block editor can't express, use an `html`-type content block inside the design.

## Personalization with Liquid

Email content uses Liquid templating. Liquid tags pass through the renderer as plain text, so use them anywhere — block text, subject, links:

```liquid
Hi {{ person.properties.first_name | default: 'there' }},
```

Marketing emails must include an unsubscribe link — render it with the built-in variables:

```html
<a href="{{ unsubscribe_url }}">Unsubscribe</a>
```

(`{{ unsubscribe_url_one_click }}` is also available for one-click list-unsubscribe flows.)

## Click tracking and opt-out

Every link is automatically rewritten through a click-tracking redirect. This breaks mobile universal links / app deeplinks, which only resolve when the href stays on their own domain. To keep a link untracked, mark its anchor (use an `html` block) with `clicktracking="off"` or `data-ph-no-track`:

```html
<a href="https://app.example.com/deeplink" data-ph-no-track>Open in app</a>
```

The marker must be on the `<a>` tag itself, not a child element. Opted-out links get no click metrics.

## Creating a template

Call `workflows-create-email-template` with:

```json
{
  "name": "Welcome email",
  "description": "Sent to new signups on day 0",
  "type": "email",
  "content": {
    "templating": "liquid",
    "email": {
      "subject": "Welcome to {{ person.properties.company | default: 'our product' }}",
      "design": { "counters": { "u_row": 1 }, "schemaVersion": 16, "body": { "rows": ["…"] } },
      "text": "Plain-text fallback of the same message"
    }
  }
}
```

- `subject` is required for email templates.
- Always provide `text` — it's the fallback for clients that block rich content and improves deliverability.
- The tool result returns an edit link into the PostHog library.
- After creating (or updating), call `workflows-show-email-template` — it renders an inline preview so the user sees the result.

### Payload mechanics

Pass the design directly in the tool call — no scratch files, no pre-validation subprocesses, no payload preview rounds. Liquid tags (`{{ }}`, `{% %}`), apostrophes, single quotes, and emoji are ordinary characters inside JSON strings; only standard JSON escaping applies. Never rewrite content to avoid them — converting Liquid's single quotes to double quotes inside markup attributes breaks the markup. If the tool call is rejected as malformed, fix the JSON escaping and resend the same content unchanged.

## Editing a template (read–modify–write)

`content` is replaced as a whole on update, never merged — and humans may have edited the design in PostHog's visual editor since you last saw it:

1. `workflows-get-email-template` — always fetch fresh; the returned `design` is the current source of truth.
2. Modify the `design` (keep subject/text alongside it).
3. `workflows-update-email-template` — send the complete `content` back. The server re-renders the sent email from the edited design.
4. `workflows-show-email-template` — render the updated template so the user sees the change; its response carries the final rendered html, so read it before describing the result.

## Using templates

- List what exists with `workflows-list-email-templates` (metadata only; fetch one for its content).
- When the user asks to see a template, call `workflows-show-email-template` — it renders an inline preview.
- Reference a template from a workflow's `function_email` action, or start a broadcast from it in the PostHog UI.
- Templates are soft-deleted by setting `deleted: true` via `workflows-update-email-template`.
