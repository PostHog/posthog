---
name: designing-email-templates
description: 'Author, save, and edit email templates in the PostHog workflows library — compose Unlayer design JSON or email-client-safe HTML with Liquid personalization, and create and round-trip-edit templates over MCP. Use when asked to design, build, update, or fix an email template for workflows, broadcasts, or campaigns.'
---

# Designing email templates

Use this skill when creating or editing email templates for PostHog workflows — broadcast campaigns and `function_email` workflow actions send the template's stored HTML.

## Two ways to author a template

- **Author the Unlayer design JSON** (`workflows-create-email-template` with `content.email.design`) — the default. The server renders the sent HTML from your design with Unlayer's own renderer (the same one the visual editor uses), so you never write or send `html`, and the template opens as editable blocks in PostHog's visual editor. Schema and a working example in [references/unlayer-design-json.md](references/unlayer-design-json.md).
- **Author raw HTML** (`content.email.html`, no `design`) — for pixel control the block editor can't express. The HTML is sent verbatim but the template is opaque to the visual editor. Prefer an `html`-type content block _inside_ a design for one custom fragment before going fully raw.

Either way, read [references/design-guidelines.md](references/design-guidelines.md) before composing — it covers committing to a design direction, typography, color, and the patterns that make an email look designed rather than generated.

## Personalization with Liquid

Liquid tags pass through the renderer as plain text, so use them anywhere — block text, subject, html:

```liquid
Hi {{ person.properties.first_name | default: "there" }},
```

Marketing emails must include an unsubscribe link — render it with the built-in variables:

```html
<a href="{{ unsubscribe_url }}">Unsubscribe</a>
```

(`{{ unsubscribe_url_one_click }}` is also available for one-click list-unsubscribe flows.)

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
      "subject": "Welcome to {{ person.properties.company | default: \"our product\" }}",
      "design": { "counters": { "u_row": 1 }, "schemaVersion": 16, "body": { "rows": ["…"] } },
      "text": "Plain-text fallback of the same message"
    }
  }
}
```

- `subject` is required for email templates.
- Omit `html` when sending a `design` — the server renders it. Sending both skips the render and trusts your `html` (that's the visual editor's own save path; don't hand-pair them yourself).
- Always provide `text` — it's the fallback for clients that block HTML and improves deliverability.
- The tool result renders an inline preview and returns an edit link into the PostHog library.

### Payload mechanics

Pass the design (or HTML) directly in the tool call — no scratch files. Liquid tags (`{{ }}`, `{% %}`) and CSS braces are ordinary characters inside JSON strings; only standard JSON escaping applies. If the tool call is rejected as malformed, fix the JSON escaping and resend the same call.

### Braces and templating engines

PostHog has two templating engines, and `hog` treats `{` as syntax — content run through it fails to compile. Keep templates on `liquid` everywhere they travel:

- `content.templating` defaults to `liquid` on templates created via the API.
- When wiring HTML into a workflow's `function_email` action inputs directly, set `"templating": "liquid"` on the email input so the braces are preserved verbatim.

## Authoring email-client-safe HTML (raw-HTML path)

Email clients render a ~2003 subset of HTML. The design path handles this for you; going raw means following these constraints yourself:

- **Layout with tables**, not flexbox/grid — nested `<table role="presentation">` is the only layout primitive Outlook respects.
- **Inline CSS on every element.** `<style>` blocks are stripped by some clients; keep them only as progressive enhancement (e.g. dark mode, mobile media queries).
- **600px max content width**, centered; single column degrades best on mobile.
- **Web-safe font stacks** with fallbacks (`Arial, Helvetica, sans-serif`); custom fonts via `@font-face` are enhancement-only.
- **Images**: absolute `https://` URLs, explicit width/height, meaningful `alt` text. No background-image-dependent content.
- **No JavaScript, no external stylesheets, no forms** — stripped or broken everywhere.
- Use real text for the message; never image-only emails.

## Editing a template (read–modify–write)

`content` is replaced as a whole on update, never merged:

1. `workflows-get-email-template` — fetch the current template.
2. Modify the `design` (keep subject/text alongside it).
3. `workflows-update-email-template` — send the complete `content` back, omitting `html` so the server re-renders it from the edited design.

For a raw-HTML template (no `design`), edit and send `html` instead — it stays canonical and the template remains detached from the visual editor.

## Using templates

- List what exists with `workflows-list-email-templates` (metadata only; fetch one for its content).
- Reference a template from a workflow's `function_email` action, or start a broadcast from it in the PostHog UI.
- Templates are soft-deleted by setting `deleted: true` via `workflows-update-email-template`.
