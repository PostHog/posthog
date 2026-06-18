# Unlayer design JSON schema

Schema for `content.email.design` — the Unlayer design document that is the source of truth for a template. You author and edit the design; on save, the server renders the sent email from it with Unlayer's export API (the same renderer PostHog's visual editor uses), and the editor opens it as editable blocks. Don't supply rendered output yourself — that's the visual editor's save path.

Adapted from [unlayer/unlayer-skills](https://github.com/unlayer/unlayer-skills) (`unlayer-export/references/design-json.md`), MIT License, Copyright (c) Unlayer.

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
    // image: { src: { url, width, height }, alt, action }
    // button: { text, href, buttonColors, size, borderRadius, ... }
    // html: { html: string }                                          — raw HTML block
  }
}
```

## Content types

`text` | `heading` | `button` | `image` | `divider` | `social` | `html` | `video` | `menu` | `timer` | `table` | `carousel`

The `html` content type is an escape hatch: a single raw-HTML block inside the design. Useful for fragments the block editor can't express, but humans can only edit it as a markup blob.

## Validation constants

| Constant       | Valid values                                                     |
| -------------- | ---------------------------------------------------------------- |
| Display modes  | `'email'` \| `'web'` \| `'popup'` \| `'document'`                |
| Text direction | `'ltr'` \| `'rtl'` \| `null`                                     |
| Alignments     | `'left'` \| `'center'` \| `'right'` \| `'justify'`               |
| Padding format | `'10px'` or `'10px 20px'` or `'10px 20px 30px 40px'` (always px) |

## Minimal working example

```json
{
  "counters": { "u_row": 1, "u_column": 1, "u_content_text": 1 },
  "schemaVersion": 16,
  "body": {
    "id": "_BZCs8S2YW",
    "rows": [
      {
        "id": "LB2ltnM2OZ",
        "cells": [1],
        "columns": [
          {
            "id": "HI7oaTElxq",
            "contents": [
              {
                "id": "PKtuJs3uBF",
                "type": "text",
                "values": {
                  "containerPadding": "10px",
                  "anchor": "",
                  "textAlign": "left",
                  "lineHeight": "140%",
                  "linkStyle": {
                    "inherit": true,
                    "linkColor": "#0000ee",
                    "linkHoverColor": "#0000ee",
                    "linkUnderline": true,
                    "linkHoverUnderline": true
                  },
                  "hideDesktop": false,
                  "displayCondition": null,
                  "_meta": { "htmlID": "u_content_text_1", "htmlClassNames": "u_content_text" },
                  "selectable": true,
                  "draggable": true,
                  "duplicatable": true,
                  "deletable": true,
                  "hideable": true,
                  "text": "<p>Hello World</p>"
                }
              }
            ],
            "values": {
              "_meta": { "htmlID": "u_column_1", "htmlClassNames": "u_column" },
              "border": {},
              "padding": "0px",
              "backgroundColor": ""
            }
          }
        ],
        "values": {
          "displayCondition": null,
          "columns": false,
          "backgroundColor": "",
          "columnsBackgroundColor": "",
          "backgroundImage": { "url": "", "fullWidth": true, "repeat": false, "center": true, "cover": false },
          "padding": "0px"
        }
      }
    ],
    "headers": [],
    "footers": [],
    "values": {
      "backgroundColor": "#ffffff",
      "contentWidth": "600px",
      "fontFamily": { "label": "Arial", "value": "arial,helvetica,sans-serif" }
    }
  }
}
```
