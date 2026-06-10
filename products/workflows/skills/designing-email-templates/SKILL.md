---
name: designing-email-templates
description: 'Author, save, and edit email templates in the PostHog workflows library — write email-client-safe HTML with Liquid personalization, create and round-trip-edit templates over MCP, or generate one from a prompt. Use when asked to design, build, update, or fix an email template for workflows, broadcasts, or campaigns.'
---

# Designing email templates

Use this skill when creating or editing email templates for PostHog workflows — broadcast campaigns and `function_email` workflow actions send the template's stored HTML verbatim.

## Two ways to produce a template

- **Author the HTML yourself** (`workflows-create-email-template`) — full control over markup and copy. The template stores exactly what you write; you remain its editor, round-tripping changes over MCP.
- **Have PostHog generate it** (`workflows-generate-email-template`) — one prompt (optionally with a brand URL) produces a complete template with an Unlayer design, so humans can edit it visually in the PostHog editor afterwards.

Pick based on who edits next: hand-off to humans in the visual editor → generate; precise control or programmatic iteration → author.

## Authoring email-client-safe HTML

Email clients render a ~2003 subset of HTML. Write a complete HTML document and follow these constraints:

- **Layout with tables**, not flexbox/grid — nested `<table role="presentation">` is the only layout primitive Outlook respects.
- **Inline CSS on every element.** `<style>` blocks are stripped by some clients; keep them only as progressive enhancement (e.g. dark mode, mobile media queries).
- **600px max content width**, centered; single column degrades best on mobile.
- **Web-safe font stacks** with fallbacks (`Arial, Helvetica, sans-serif`); custom fonts via `@font-face` are enhancement-only.
- **Images**: absolute `https://` URLs, explicit width/height, meaningful `alt` text. No background-image-dependent content.
- **No JavaScript, no external stylesheets, no forms** — stripped or broken everywhere.
- Use real text for the message; never image-only emails.

## Personalization with Liquid

Set `content.templating` to `liquid`. Subject, html, and text all support Liquid:

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
      "html": "<!DOCTYPE html>…full document…",
      "text": "Plain-text fallback of the same message"
    }
  }
}
```

- `subject` is required for email templates.
- Always provide `text` — it's the fallback for clients that block HTML and improves deliverability.
- The tool result renders an inline preview and returns an edit link into the PostHog library.

## Editing a template (read–modify–write)

`content` is replaced as a whole on update, never merged:

1. `workflows-get-email-template` — fetch the current template.
2. Modify the `content.email` object (keep subject/html/text together).
3. `workflows-update-email-template` — send the complete `content` back.

Templates saved from PostHog's visual editor also carry `content.email.design` (Unlayer design JSON). Sending `content` without `design` makes your HTML canonical and detaches the template from the visual editor's saved design — do that deliberately when taking over authorship; otherwise include the fetched `design` untouched and limit your changes to metadata (`name`, `description`, `message_category`).

## Using templates

- List what exists with `workflows-list-email-templates` (metadata only; fetch one for its HTML).
- Reference a template from a workflow's `function_email` action, or start a broadcast from it in the PostHog UI.
- Templates are soft-deleted by setting `deleted: true` via `workflows-update-email-template`.
