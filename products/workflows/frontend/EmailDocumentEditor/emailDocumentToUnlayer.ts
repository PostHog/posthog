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
const ROW_VALUES: UnlayerValues = {
    columns: false,
    columnsBackgroundColor: '',
    backgroundColor: '',
    backgroundImage: { url: '' },
    padding: '0px',
}

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

function addSides(value: EmailSides, extra: EmailSides): EmailSides {
    return {
        top: number(value.top, 0) + extra.top,
        right: number(value.right, 0) + extra.right,
        bottom: number(value.bottom, 0) + extra.bottom,
        left: number(value.left, 0) + extra.left,
    }
}

function webLink(href: string): UnlayerValues {
    return {
        name: 'web',
        attrs: { href: '{{href}}', target: '{{target}}' },
        values: { href, target: '_blank' },
    }
}

function imageContent(node: JSONContent, contentWidth: number, outer: EmailSides): Content | null {
    const style = styleOf(node)
    const padding = style.padding ?? NO_SIDES
    const available = Math.max(1, contentWidth - number(padding.left, 0) - number(padding.right, 0))
    const src = String(node.attrs?.src ?? '')
    if (!src) {
        return null
    }
    const width = style.width ?? node.attrs?.naturalWidth
    // An image at its own size, capped by its column, is the old editor's automatic width. A fixed percentage
    // instead would shrink it on phones, where this editor lets it fill the screen.
    const naturalWidth = number(node.attrs?.naturalWidth, 0)
    const autoWidth = !style.width || (naturalWidth > 0 && number(style.width, 0) === Math.min(naturalWidth, available))
    const href = safeEmailLink(node.attrs?.href)
    return {
        type: 'image',
        values: {
            src: {
                url: src,
                width: number(width, contentWidth),
                ...(node.attrs?.naturalHeight ? { height: number(node.attrs.naturalHeight, 0) } : {}),
                autoWidth,
                ...(!autoWidth
                    ? {
                          maxWidth: `${Math.min(100, Math.round((number(style.width, available) / available) * 1000) / 10)}%`,
                      }
                    : {}),
            },
            altText: String(node.attrs?.alt ?? ''),
            textAlign: style.textAlign ?? 'left',
            containerPadding: sidesCss(addSides(padding, outer)),
            ...(href ? { action: webLink(href) } : {}),
        },
    }
}

function buttonBorder(style: EmailBlockStyle, background: string): UnlayerValues {
    if (!style.borderWidth) {
        return {}
    }
    const side = { width: `${style.borderWidth}px`, style: 'solid', color: style.borderColor ?? background }
    const border: UnlayerValues = {}
    for (const name of ['Top', 'Right', 'Bottom', 'Left']) {
        border[`border${name}Width`] = side.width
        border[`border${name}Style`] = side.style
        border[`border${name}Color`] = side.color
    }
    return { border }
}

function buttonSize(style: EmailBlockStyle): UnlayerValues {
    return style.buttonWidth
        ? { autoWidth: false, width: `${Math.min(100, number(style.buttonWidth, 100))}%` }
        : { autoWidth: true, width: '100%' }
}

function buttonText(style: EmailBlockStyle, page: EmailPageStyle): UnlayerValues {
    return {
        fontSize: `${number(style.fontSize, page.fontSize)}px`,
        fontWeight: number(style.fontWeight, 600),
        lineHeight: `${number(style.lineHeight, 120)}%`,
        ...(style.fontFamily ? { fontFamily: { label: style.fontFamily, value: style.fontFamily } } : {}),
    }
}

function buttonContent(node: JSONContent, page: EmailPageStyle, outer: EmailSides): Content | null {
    const style = styleOf(node)
    const color = style.color ?? page.buttonTextColor
    const text = oldEditorInlineHtml(node.content, { ...page, linkColor: color })
    if (!text) {
        return null
    }
    const background = style.backgroundColor ?? page.buttonBackgroundColor
    const href = safeEmailLink(node.attrs?.href)
    return {
        type: 'button',
        values: {
            text,
            ...(href ? { href: webLink(href) } : {}),
            buttonColors: { color, backgroundColor: background, hoverColor: color, hoverBackgroundColor: background },
            size: buttonSize(style),
            padding: `${number(style.innerPaddingY, 12)}px ${number(style.innerPaddingX, 24)}px`,
            ...buttonText(style, page),
            borderRadius: `${number(style.borderRadius, page.buttonBorderRadius)}px`,
            ...buttonBorder(style, background),
            textAlign: style.textAlign ?? 'left',
            containerPadding: sidesCss(
                addSides(style.padding ?? { ...DEFAULT_BLOCK_SIDES, top: 12, bottom: 12 }, outer)
            ),
        },
    }
}

function dividerContent(node: JSONContent, outer: EmailSides): Content {
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
            containerPadding: sidesCss(addSides(style.padding ?? DEFAULT_BLOCK_SIDES, outer)),
        },
    }
}

function textContent(node: JSONContent, page: EmailPageStyle, contentWidth: number, outer: EmailSides): Content | null {
    const style = styleOf(node)
    const { kind, html } = oldEditorBlockHtml(node, page, contentWidth)
    if (kind === 'html') {
        return html ? { type: 'html', values: { html, containerPadding: sidesCss(outer) } } : null
    }
    return {
        type: 'text',
        values: {
            text: html,
            textAlign: style.textAlign ?? 'left',
            containerPadding: sidesCss(addSides(style.padding ?? DEFAULT_BLOCK_SIDES, outer)),
            ...(style.backgroundColor ? { backgroundColor: style.backgroundColor } : {}),
        },
    }
}

function blockContent(
    node: JSONContent,
    page: EmailPageStyle,
    contentWidth: number,
    outer: EmailSides = NO_SIDES
): Content | null {
    switch (node.type) {
        case 'emailImage':
            return imageContent(node, contentWidth, outer)
        case 'emailButton':
            return buttonContent(node, page, outer)
        case 'horizontalRule':
            return dividerContent(node, outer)
        case 'emailHtml':
            return {
                type: 'html',
                values: {
                    html: String(node.attrs?.html ?? ''),
                    containerPadding: sidesCss(addSides(styleOf(node).padding ?? NO_SIDES, outer)),
                },
            }
        default:
            return textContent(node, page, contentWidth, outer)
    }
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
    outer: EmailSides
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
        const columnOuter = {
            ...outer,
            left: index === 0 ? outer.left : 0,
            right: index === columns.length - 1 ? outer.right : 0,
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
            padding: sidesCss(addSides(padding, columnOuter)),
            backgroundColor: columnStyle.backgroundColor ?? style.backgroundColor ?? page.bodyBackgroundColor,
            border: {},
        })
    })
    return row(unlayerColumns, ratios, ids, {
        ...ROW_VALUES,
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
    // The body's padding goes on the blocks next to it. Rows with padding of their own would come back to this editor
    // as sections around each block.
    const outer = (index: number): EmailSides => ({
        top: index === 0 ? number(padding.top, 0) : 0,
        right: number(padding.right, 0),
        bottom: index === blocks.length - 1 ? number(padding.bottom, 0) : 0,
        left: number(padding.left, 0),
    })
    const rows = blocks
        .map((block, index) => {
            if (block.type === 'emailColumns') {
                return columnsRow(block, page, contentWidth, ids, outer(index))
            }
            const content = blockContent(block, page, contentWidth, outer(index))
            return content
                ? row(
                      [
                          column([content], ids, {
                              padding: '0px',
                              backgroundColor: page.bodyBackgroundColor,
                              border: {},
                          }),
                      ],
                      [1],
                      ids,
                      ROW_VALUES
                  )
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
