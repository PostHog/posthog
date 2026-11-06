# Email document editor

The TipTap editor that replaces Unlayer for native emails, behind the `workflows-email-document-editor` flag.

## What is stored

Nothing about the send path changes: `content.email.html` and `.text` are still what goes out.
The editor's state lives in `design`, which is never compiled or sent:

```text
design = {
  ...an old-editor design with one HTML block holding the rendered html,
  emailDocument: { version: 1, doc: <TipTap JSON, page style in doc.attrs.page> }
}
```

This shape does three things:

- Everything that reads `design` keeps working: the old editor, the MCP tools, `validate_design`, and save with flag off. With the flag off, the email opens in the old editor as one HTML block.
- A stale document is detectable. The HTML block holds the html the document rendered. If `html` differs, something else changed the email, so the document is ignored and the old editor opens. See `emailDocumentFromValue`.
- `html_wrap_design_needs_refresh` (backend) and `editorDesignForEmail` (frontend) refresh a stale wrap and drop the document.

## Which editor opens

`usesDocumentEditor` in `emailTemplaterLogic` decides, and only with the flag on:

| Email                                       | Editor                                  |
| ------------------------------------------- | --------------------------------------- |
| Blank, or the untouched new template sample | New                                     |
| Has a current `emailDocument`               | New                                     |
| Anything else                               | Old, with a "Try the new editor" prompt |

The prompt runs `unlayerToEmailDocument` and shows both versions side by side. Nothing changes until a person accepts.
Anything it can't convert faithfully is reported, and the email stays on the old editor. The one exception is a button's hover color, which the prompt says won't be kept before a person accepts.

The new editor reaches `emailTemplaterLogic` through `emailEditorAdapter`, which implements the part of Unlayer's API the logic calls. Saving, live changes and external edits share one code path.

## Email output

`renderEmailHtml` writes tables and inline styles. Columns are inline-blocks capped at their width, so they stack on a phone without a media query, with ghost tables for Outlook. Liquid passes through unescaped outside attributes.
