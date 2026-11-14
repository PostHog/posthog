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

| Email                                       | Editor                                                   |
| ------------------------------------------- | -------------------------------------------------------- |
| Blank, or the untouched new template sample | New                                                      |
| Has a current `emailDocument`               | New                                                      |
| Anything else, if it converts               | New, converted when opened                               |
| Anything else, if it doesn't                | Old, with a note saying why                              |
| The person chose "Use old editor"           | Old, in this browser, until they choose "Use new editor" |

Opening never changes an email. `unlayerToEmailDocument` runs when it opens, and the stored email stays exactly as it is until someone edits it.
Saving without editing keeps the stored html, text and design as they were.
Anything the conversion can't hold faithfully keeps the email on the old editor, or stays as an HTML block when it's only part of a text block. Button hover colors are the exception: the note above the editor says they won't be kept.

The new editor reaches `emailTemplaterLogic` through `emailEditorAdapter`, which implements the part of Unlayer's API the logic calls. Saving, live changes and external edits share one code path.

## Email output

`renderEmailHtml` writes tables and inline styles. Columns are inline-blocks capped at their width, so they stack on a phone without a media query, with ghost tables for Outlook. Liquid passes through unescaped outside attributes.
