# Unlayer design JSON schema

Schema for `content.email.design` — the Unlayer design document that is the source of truth for a template. You author and edit the design; on save, the server renders the sent email from it with Unlayer's export API (the same renderer PostHog's visual editor uses), and the editor opens it as editable blocks. Don't supply rendered output yourself — that's the visual editor's save path.

Adapted from [unlayer/unlayer-skills](https://github.com/unlayer/unlayer-skills) (`unlayer-export/references/design-json.md`), MIT License, Copyright (c) Unlayer.

## Contents

- Top-level structure
- Body values
- Row structure
- Column structure
- Content item structure
- Content types
- Native blocks and spacing
- Validation constants
- Minimal working example
- Editing blocks with operations

## Top-level structure

```typescript
interface JSONTemplate {
  counters: Record<string, number> // e.g., { u_row: 3, u_column: 4, u_content_text: 5 }
  schemaVersion: number // 16
  body: {
    id: string // any unique string, e.g., "_BZCs8S2YW"
    rows: Row[]
    headers: Row[] // usually []
    footers: Row[] // usually []
    values: BodyValues
  }
}
```

IDs are arbitrary unique strings. `counters` tracks the highest `_meta.htmlID` suffix per element type (`u_row`, `u_column`, `u_content_text`, `u_content_button`, …) so the editor can number new elements — keep it consistent with the `_meta.htmlID`s you emit.

## Body values

```typescript
interface BodyValues {
  backgroundColor: string
  contentWidth: string // '600px'
  fontFamily: { label: string; value: string }
  textColor: string
  linkStyle: {
    inherit: boolean
    linkColor: string
    linkHoverColor: string
    linkUnderline: boolean
    linkHoverUnderline: boolean
  }
}
```

## Row structure

```typescript
interface Row {
  id: string
  cells: number[] // Column ratios: [1,1] = 50/50, [1,2] = 33/66
  columns: Column[]
  values: {
    displayCondition: object | null
    columns: boolean // false = locked columns
    backgroundColor: string
    columnsBackgroundColor: string
    backgroundImage: {
      url: string
      fullWidth: boolean
      repeat: boolean
      center: boolean
      cover: boolean
    }
    padding: string // "0px" or "10px 20px 10px 20px"
    _meta: { htmlID: string; htmlClassNames: string }
  }
}
```

## Column structure

```typescript
interface Column {
  id: string
  contents: ContentItem[]
  values: {
    _meta: { htmlID: string; htmlClassNames: string }
    border: object
    padding: string
    backgroundColor: string
  }
}
```

## Content item structure

Shared properties common to all content items; each tool type adds its own fields to `values`.

```typescript
interface ContentItem {
  id: string
  type: string // See content types below
  values: {
    // --- Shared properties (all tools) ---
    containerPadding: string
    anchor: string
    textAlign: string // 'left' | 'center' | 'right'
    lineHeight: string // '140%'
    linkStyle: {
      inherit: boolean
      linkColor: string
      linkHoverColor: string
      linkUnderline: boolean
      linkHoverUnderline: boolean
    }
    hideDesktop: boolean
    displayCondition: object | null
    _meta: { htmlID: string; htmlClassNames: string }
    selectable: boolean
    draggable: boolean
    duplicatable: boolean
    deletable: boolean
    hideable: boolean
    // --- Tool-specific properties vary per type ---
    // text/heading: { text: string }                                  — text is an HTML fragment
    // image: { src: { url, width, height }, alt, action }             — url from media-image-upload-complete or media-images-list, see SKILL.md#images
    // button: { text, href: { name: 'web', values: { href, target } }, buttonColors, size, borderRadius, ... }
    // divider: { width, border: { borderTopWidth, borderTopStyle, borderTopColor } }
    // html: { html: string }                                          — raw HTML block
  }
}
```

## Content types

`text` | `heading` | `button` | `image` | `divider` | `social` | `html` | `video` | `menu` | `timer` | `table` | `carousel`

The `html` content type is an escape hatch: a single raw-HTML block inside the design. Useful for fragments the block editor can't express, but humans can only edit it as a markup blob.

## Native blocks and spacing

Compose every email from native blocks: a `heading`, one `text` block per paragraph, a `button` per call to action, and a `divider` between sections. People edit each block on its own in the visual editor, and patch operations address it by id.

- **Paragraphs** are `text` blocks, one paragraph each. The editor's Paragraph block (`type: "paragraph"`) needs editor-only `textJson` state and loads empty without it.
- **Spacing values** live on the block: `containerPadding` on every block, plus `fontSize` and `lineHeight` on `heading` and `text`. `"8px 24px"`, `"16px"`, and `"150%"` on every paragraph give a 16px gap.
- **Markup spacing** shows only in the inbox: the editor canvas strips `<p>` margins, so spacing written as markup looks cramped in the editor. The spacing values are the one place spacing goes.
- **Defaults** fill a missing spacing value (`10px` padding, `14px` text), so that block sits closer and smaller than its neighbors. Every block, including one added later by a patch operation, carries its own spacing values.
- **Button links** are an object: `"href": { "name": "web", "values": { "href": "https://example.com/setup", "target": "_blank" } }`. The editor shows the URL in the button's own link field.

Write only these values. The editor fills every other key (`anchor`, `linkStyle`, `hideDesktop`, `selectable`, and so on) with its default when it loads the design.

## Validation constants

| Constant       | Valid values                                                     |
| -------------- | ---------------------------------------------------------------- |
| Display modes  | `'email'` \| `'web'` \| `'popup'` \| `'document'`                |
| Text direction | `'ltr'` \| `'rtl'` \| `null`                                     |
| Alignments     | `'left'` \| `'center'` \| `'right'` \| `'justify'`               |
| Padding format | `'10px'` or `'10px 20px'` or `'10px 20px 30px 40px'` (always px) |

## Minimal working example

A heading, two paragraphs, a button, and a divider, spaced as described above:

```json
{
  "counters": {
    "u_row": 1,
    "u_column": 1,
    "u_content_heading": 1,
    "u_content_text": 2,
    "u_content_button": 1,
    "u_content_divider": 1
  },
  "schemaVersion": 16,
  "body": {
    "id": "welcome-body",
    "headers": [],
    "footers": [],
    "values": {
      "backgroundColor": "#ffffff",
      "contentWidth": "600px",
      "textColor": "#1d1f27",
      "fontFamily": { "label": "Arial", "value": "arial,helvetica,sans-serif" }
    },
    "rows": [
      {
        "id": "row-main",
        "cells": [1],
        "values": { "padding": "0px", "_meta": { "htmlID": "u_row_1", "htmlClassNames": "u_row" } },
        "columns": [
          {
            "id": "col-main",
            "values": { "_meta": { "htmlID": "u_column_1", "htmlClassNames": "u_column" } },
            "contents": [
              {
                "id": "heading-welcome",
                "type": "heading",
                "values": {
                  "headingType": "h1",
                  "text": "Welcome, {{ person.properties.first_name | default: 'there' }}",
                  "fontSize": "26px",
                  "lineHeight": "130%",
                  "textAlign": "left",
                  "containerPadding": "32px 24px 8px",
                  "_meta": { "htmlID": "u_content_heading_1", "htmlClassNames": "u_content_heading" }
                }
              },
              {
                "id": "text-intro",
                "type": "text",
                "values": {
                  "text": "<p>Thanks for signing up. Over the next week we will send you a few short emails that help you get set up.</p>",
                  "fontSize": "16px",
                  "lineHeight": "150%",
                  "textAlign": "left",
                  "containerPadding": "8px 24px",
                  "_meta": { "htmlID": "u_content_text_1", "htmlClassNames": "u_content_text" }
                }
              },
              {
                "id": "text-next-step",
                "type": "text",
                "values": {
                  "text": "<p>Start by connecting your first data source. Everything else builds on it.</p>",
                  "fontSize": "16px",
                  "lineHeight": "150%",
                  "textAlign": "left",
                  "containerPadding": "8px 24px",
                  "_meta": { "htmlID": "u_content_text_2", "htmlClassNames": "u_content_text" }
                }
              },
              {
                "id": "button-setup",
                "type": "button",
                "values": {
                  "text": "Connect a data source",
                  "href": { "name": "web", "values": { "href": "https://example.com/setup", "target": "_blank" } },
                  "buttonColors": {
                    "color": "#FFFFFF",
                    "backgroundColor": "#1d4aff",
                    "hoverColor": "#FFFFFF",
                    "hoverBackgroundColor": "#1d4aff"
                  },
                  "fontSize": "16px",
                  "padding": "12px 24px",
                  "borderRadius": "6px",
                  "textAlign": "left",
                  "containerPadding": "16px 24px",
                  "_meta": { "htmlID": "u_content_button_1", "htmlClassNames": "u_content_button" }
                }
              },
              {
                "id": "divider-footer",
                "type": "divider",
                "values": {
                  "width": "100%",
                  "border": { "borderTopWidth": "1px", "borderTopStyle": "solid", "borderTopColor": "#E5E7EB" },
                  "textAlign": "center",
                  "containerPadding": "16px 24px",
                  "_meta": { "htmlID": "u_content_divider_1", "htmlClassNames": "u_content_divider" }
                }
              }
            ]
          }
        ]
      }
    ]
  }
}
```

## Editing blocks with operations

`workflows-patch-action-email` and `workflows-patch-email-template` address blocks by id. An `update_content` patch deep-merges into the block, so this changes only the button URL and keeps `name` and `target`:

```json
{
  "op": "update_content",
  "id": "button-setup",
  "patch": { "values": { "href": { "values": { "href": "https://example.com/get-started" } } } }
}
```

A paragraph added with `add_content` carries the same spacing values as the other paragraphs:

```json
{
  "op": "add_content",
  "column_id": "col-main",
  "index": 3,
  "content": {
    "type": "text",
    "values": {
      "text": "<p>Questions? Reply to this email and we will help.</p>",
      "fontSize": "16px",
      "lineHeight": "150%",
      "textAlign": "left",
      "containerPadding": "8px 24px"
    }
  }
}
```
