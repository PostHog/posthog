import type { JSONContent } from '@tiptap/core'

import { EmailBlockStyle, EmailPageStyle, EmailSides, resolvePageStyle } from './emailDocument'
import {
    oldEditorBlockHtml,
    oldEditorInlineHtml,
    safeEmailLink,
    withoutTrailingEmptyParagraphs,
} from './renderEmailHtml'

const DEFAULT_BLOCK_SIDES: EmailSides = { top: 8, right: 0, bottom: 8, left: 0 }
const NO_SIDES: EmailSides = { top: 0, right: 0, bottom: 0, left: 0 }

type UnlayerValues = Record<string, any>

interface Content {
    type: string
    values: UnlayerValues
}

/** Hands out the ids the old editor numbers its rows, columns and blocks with, so the same email always gets the same design. */
class Ids {
    counters: Record<string, number> = {}

    next(kind: string): { id: string; meta: { htmlID: string; htmlClassNames: string } } {
        const count = (this.counters[kind] ?? 0) + 1
        this.counters[kind] = count
        return { id: `${kind}_${count}`, meta: { htmlID: `${kind}_${count}`, htmlClassNames: kind } }
    }
}

function styleOf(node: JSONContent): EmailBlockStyle {
    return (node.attrs?.emailStyle as EmailBlockStyle | null | undefined) ?? {}
}

function number(value: unknown, fallback: number): number {
    const parsed = typeof value === 'number' ? value : Number(value)
    return Number.isFinite(parsed) ? Math.max(0, parsed) : fallback
}

function sidesCss(value: EmailSides): string {
    return `${number(value.top, 0)}px ${number(value.right, 0)}px ${number(value.bottom, 0)}px ${number(value.left, 0)}px`
}

function webLink(href: string): UnlayerValues {
    return {
        name: 'web',
        attrs: { href: '{{href}}', target: '{{target}}' },
        values: { href, target: '_blank' },
    }
}

function imageContent(node: JSONContent, contentWidth: number): Content | null {
    const style = styleOf(node)
    const src = String(node.attrs?.src ?? '')
    if (!src) {
        return null
    }
    const width = style.width ?? node.attrs?.naturalWidth
    const href = safeEmailLink(node.attrs?.href)
    return {
        type: 'image',
        values: {
            src: {
                url: src,
                width: number(width, contentWidth),
                ...(node.attrs?.naturalHeight ? { height: number(node.attrs.naturalHeight, 0) } : {}),
                autoWidth: !style.width,
                ...(style.width
                    ? {
                          maxWidth: `${Math.min(100, Math.round((number(style.width, contentWidth) / contentWidth) * 100))}%`,
                      }
                    : {}),
            },
            altText: String(node.attrs?.alt ?? ''),
            textAlign: style.textAlign ?? 'left',
            containerPadding: sidesCss(style.padding ?? NO_SIDES),
            ...(href ? { action: webLink(href) } : {}),
        },
    }
}

function buttonContent(node: JSONContent, page: EmailPageStyle): Content | null {
    const style = styleOf(node)
    const text = oldEditorInlineHtml(node.content, { ...page, linkColor: style.color ?? page.buttonTextColor })
    if (!text) {
        return null
    }
    const color = style.color ?? page.buttonTextColor
    const background = style.backgroundColor ?? page.buttonBackgroundColor
    const href = safeEmailLink(node.attrs?.href)
    return {
        type: 'button',
        values: {
            text,
            ...(href ? { href: webLink(href) } : {}),
            buttonColors: { color, backgroundColor: background, hoverColor: color, hoverBackgroundColor: background },
            size: style.buttonWidth
                ? { autoWidth: false, width: `${Math.min(100, number(style.buttonWidth, 100))}%` }
                : { autoWidth: true, width: '100%' },
            padding: `${number(style.innerPaddingY, 12)}px ${number(style.innerPaddingX, 24)}px`,
            fontSize: `${number(style.fontSize, page.fontSize)}px`,
            fontWeight: number(style.fontWeight, 600),
            lineHeight: `${number(style.lineHeight, 120)}%`,
            borderRadius: `${number(style.borderRadius, page.buttonBorderRadius)}px`,
            ...(style.borderWidth
                ? {
                      border: {
                          borderTopWidth: `${style.borderWidth}px`,
                          borderTopStyle: 'solid',
                          borderTopColor: style.borderColor ?? background,
                          borderRightWidth: `${style.borderWidth}px`,
                          borderRightStyle: 'solid',
                          borderRightColor: style.borderColor ?? background,
                          borderBottomWidth: `${style.borderWidth}px`,
                          borderBottomStyle: 'solid',
                          borderBottomColor: style.borderColor ?? background,
                          borderLeftWidth: `${style.borderWidth}px`,
                          borderLeftStyle: 'solid',
                          borderLeftColor: style.borderColor ?? background,
                      },
                  }
                : {}),
            ...(style.fontFamily ? { fontFamily: { label: style.fontFamily, value: style.fontFamily } } : {}),
            textAlign: style.textAlign ?? 'left',
            containerPadding: sidesCss(style.padding ?? { ...DEFAULT_BLOCK_SIDES, top: 12, bottom: 12 }),
        },
    }
}

function dividerContent(node: JSONContent): Content {
    const style = styleOf(node)
    return {
        type: 'divider',
        values: {
            width: `${Math.min(100, number(style.width, 100) || 100)}%`,
            border: {
                borderTopWidth: `${number(style.lineWidth, 1) || 1}px`,
                borderTopStyle: 'solid',
                borderTopColor: style.borderColor ?? '#dddddd',
            },
            textAlign: style.textAlign ?? 'center',
            containerPadding: sidesCss(style.padding ?? DEFAULT_BLOCK_SIDES),
        },
    }
}

function blockContent(node: JSONContent, page: EmailPageStyle, contentWidth: number): Content | null {
    switch (node.type) {
        case 'emailImage':
            return imageContent(node, contentWidth)
        case 'emailButton':
            return buttonContent(node, page)
        case 'horizontalRule':
            return dividerContent(node)
        case 'emailHtml':
            return {
                type: 'html',
                values: {
                    html: String(node.attrs?.html ?? ''),
                    containerPadding: sidesCss(styleOf(node).padding ?? NO_SIDES),
                },
            }
    }
    const style = styleOf(node)
    const { kind, html } = oldEditorBlockHtml(node, page, contentWidth)
    if (kind === 'text') {
        return {
            type: 'text',
            values: {
                text: html,
                textAlign: style.textAlign ?? 'left',
                containerPadding: sidesCss(style.padding ?? DEFAULT_BLOCK_SIDES),
                ...(style.backgroundColor ? { backgroundColor: style.backgroundColor } : {}),
            },
        }
    }
    return html ? { type: 'html', values: { html, containerPadding: '0px' } } : null
}

function withMeta(content: Content, ids: Ids): Record<string, any> {
    const { id, meta } = ids.next(`u_content_${content.type}`)
    return { id, type: content.type, values: { ...content.values, _meta: meta } }
}

function column(contents: Content[], ids: Ids, values: UnlayerValues): Record<string, any> {
    const { id, meta } = ids.next('u_column')
    return { id, contents: contents.map((content) => withMeta(content, ids)), values: { ...values, _meta: meta } }
}

function row(columns: Record<string, any>[], cells: number[], ids: Ids, values: UnlayerValues): Record<string, any> {
    const { id, meta } = ids.next('u_row')
    return { id, cells, columns, values: { ...values, _meta: meta } }
}

function columnsRow(
    node: JSONContent,
    page: EmailPageStyle,
    contentWidth: number,
    ids: Ids,
    rowValues: UnlayerValues
): Record<string, any> {
    const style = styleOf(node)
    const columns = node.content ?? []
    const ratios = columns.map((child) => number(child.attrs?.ratio, 1) || 1)
    const total = ratios.reduce((sum, ratio) => sum + ratio, 0) || 1
    const gap = columns.length > 1 ? number(style.columnGap, 16) : 0
    const unlayerColumns = columns.map((child, index) => {
        const columnStyle = styleOf(child)
        const width = Math.max(1, Math.floor((contentWidth * ratios[index]) / total))
        const padding = columnStyle.padding ?? {
            ...NO_SIDES,
            left: index === 0 ? 0 : gap / 2,
            right: index === columns.length - 1 ? 0 : gap / 2,
        }
        const innerWidth = Math.max(1, width - number(padding.left, 0) - number(padding.right, 0))
        const contents = withoutTrailingEmptyParagraphs(child.content ?? [])
            .map((block) =>
                block.type === 'emailColumns'
                    ? ({
                          type: 'html',
                          values: { html: oldEditorBlockHtml(block, page, innerWidth).html, containerPadding: '0px' },
                      } as Content)
                    : blockContent(block, page, innerWidth)
            )
            .filter((content): content is Content => !!content)
        return column(contents, ids, {
            padding: sidesCss(padding),
            backgroundColor: columnStyle.backgroundColor ?? '',
            border: {},
        })
    })
    return row(unlayerColumns, ratios, ids, {
        ...rowValues,
        ...(style.backgroundColor ? { columnsBackgroundColor: style.backgroundColor } : {}),
    })
}

/**
 * The email as an old-editor design, with the same blocks in the same order, so turning the new editor off leaves
 * every email editable there. The html that goes out is still the new editor's: this design only takes over once
 * someone edits the email in the old editor.
 */
export function emailDocumentToUnlayer(doc: JSONContent): Record<string, any> {
    const page = resolvePageStyle(doc.attrs?.page)
    const ids = new Ids()
    const padding = page.bodyPadding
    const contentWidth = Math.max(1, page.bodyWidth - number(padding.left, 0) - number(padding.right, 0))
    const blocks = withoutTrailingEmptyParagraphs(doc.content ?? [])
    const rowValues = (index: number): UnlayerValues => ({
        columns: false,
        columnsBackgroundColor: page.bodyBackgroundColor,
        backgroundColor: '',
        backgroundImage: { url: '' },
        padding: `${index === 0 ? number(padding.top, 0) : 0}px ${number(padding.right, 0)}px ${
            index === blocks.length - 1 ? number(padding.bottom, 0) : 0
        }px ${number(padding.left, 0)}px`,
    })
    const rows = blocks
        .map((block, index) => {
            if (block.type === 'emailColumns') {
                return columnsRow(block, page, contentWidth, ids, rowValues(index))
            }
            const content = blockContent(block, page, contentWidth)
            return content
                ? row([column([content], ids, { padding: '0px', border: {} })], [1], ids, rowValues(index))
                : null
        })
        .filter((built): built is Record<string, any> => !!built)

    return {
        counters: ids.counters,
        schemaVersion: 16,
        body: {
            id: 'email-document-body',
            headers: [],
            footers: [],
            rows,
            values: {
                backgroundColor: page.backgroundColor,
                contentWidth: `${page.bodyWidth}px`,
                contentAlign: page.align,
                fontFamily: { label: page.fontFamily, value: page.fontFamily },
                textColor: page.textColor,
                linkStyle: {
                    body: true,
                    linkColor: page.linkColor,
                    linkHoverColor: page.linkColor,
                    linkUnderline: true,
                    linkHoverUnderline: true,
                },
                preheaderText: page.previewText,
                _meta: { htmlID: 'u_body', htmlClassNames: 'u_body' },
            },
        },
    }
}
