import { JSONContent, generateJSON } from '@tiptap/core'

import {
    EmailBlockStyle,
    EmailDocument,
    EMAIL_DOCUMENT_VERSION,
    EmailPageStyle,
    EmailSides,
    EmailTextAlign,
} from './emailDocument'
import { buildEmailExtensions } from './emailExtensions'
import { parseLiquidOutput } from './emailVariables'

const UNSUPPORTED_CONTENT: Record<string, string> = {
    menu: 'menus',
    video: 'videos',
    timer: 'countdown timers',
    table: 'tables',
    carousel: 'carousels',
}
const LIQUID_OUTPUT = /(\{\{[^{}]+?\}\})/g

export interface EmailDocumentConversion {
    document: EmailDocument | null
    /** Why it can't be converted, in words for the person who owns the template. Empty when it can. */
    unsupported: string[]
}

function parsePx(value: unknown): number | undefined {
    const number = parseFloat(String(value ?? ''))
    return Number.isFinite(number) ? number : undefined
}

function parseSides(value: unknown): EmailSides | undefined {
    if (typeof value !== 'string' || !value.trim()) {
        return undefined
    }
    const parts = value
        .trim()
        .split(/\s+/)
        .map((part) => parseFloat(part) || 0)
    const [top, right = top, bottom = top, left = right] = parts
    return { top, right, bottom, left }
}

function align(value: unknown): EmailTextAlign | undefined {
    return value === 'left' || value === 'center' || value === 'right' ? value : undefined
}

function compact(style: EmailBlockStyle): EmailBlockStyle | null {
    const entries = Object.entries(style).filter(([, value]) => value !== undefined && value !== '')
    return entries.length ? (Object.fromEntries(entries) as EmailBlockStyle) : null
}

function chipsInText(nodes: JSONContent[] | undefined): JSONContent[] | undefined {
    return nodes?.flatMap((node) => {
        if (node.type === 'text' && node.text && LIQUID_OUTPUT.test(node.text)) {
            LIQUID_OUTPUT.lastIndex = 0
            return node.text
                .split(LIQUID_OUTPUT)
                .filter(Boolean)
                .map((part): JSONContent => {
                    const match = part.match(/^\{\{\s*([^{}]+?)\s*\}\}$/)
                    return match
                        ? { type: 'variable', attrs: parseLiquidOutput(match[1]), marks: node.marks }
                        : { ...node, text: part }
                })
        }
        LIQUID_OUTPUT.lastIndex = 0
        return node.content ? [{ ...node, content: chipsInText(node.content) }] : [node]
    })
}

function textBlocks(html: string, style: EmailBlockStyle): JSONContent[] {
    const extensions = buildEmailExtensions('')
    const content = chipsInText(generateJSON(html, extensions).content) ?? []
    const padding = style.padding
    return content.map((node, index) => {
        const isFirst = index === 0
        const isLast = index === content.length - 1
        const blockStyle = compact({
            ...style,
            padding: padding
                ? { ...padding, top: isFirst ? padding.top : 0, bottom: isLast ? padding.bottom : 0 }
                : undefined,
        })
        return { ...node, attrs: { ...node.attrs, emailStyle: blockStyle } }
    })
}

function textStyleFrom(values: Record<string, any>): EmailBlockStyle {
    return {
        color: values.color || undefined,
        fontSize: parsePx(values.fontSize),
        lineHeight: parsePx(values.lineHeight),
        letterSpacing: parsePx(values.letterSpacing) || undefined,
        textAlign: align(values.textAlign),
        padding: parseSides(values.containerPadding),
    }
}

/** The same hosted icons the old editor's export links to, as an HTML block, so a footer looks the way it did. */
function socialIconsHtml(values: Record<string, any>): string {
    const iconType = String(values.icons?.iconType ?? 'circle-black').replace(/[^a-z-]/gi, '')
    const size = parsePx(values.iconSize) ?? 32
    const spacing = parsePx(values.spacing) ?? 5
    const cells = (values.icons?.icons ?? [])
        .map((icon: { name?: string; url?: string }) => {
            const name = String(icon.name ?? '')
            const file = name.toLowerCase().replace(/[^a-z0-9]/g, '')
            const href = String(icon.url ?? '').replace(/"/g, '&quot;')
            return `<td style="padding:0 ${spacing / 2}px"><a href="${href}" target="_blank"><img src="https://cdn.tools.unlayer.com/social/icons/${iconType}/${file}.png" alt="${name.replace(/"/g, '&quot;')}" width="${size}" height="${size}" style="display:block;border:0" /></a></td>`
        })
        .join('')
    return `<table role="presentation" align="${align(values.align) ?? 'center'}" cellpadding="0" cellspacing="0" border="0"><tr>${cells}</tr></table>`
}

function convertContent(content: Record<string, any>, contentWidth: number, unsupported: Set<string>): JSONContent[] {
    const values = content.values ?? {}
    if (values.displayCondition) {
        unsupported.add('blocks shown on a condition')
    }
    if (values.hideDesktop || values.hideMobile) {
        unsupported.add('blocks hidden on some screen sizes')
    }
    switch (content.type) {
        case 'text':
        case 'paragraph':
            return textBlocks(String(values.text ?? ''), textStyleFrom(values))
        case 'heading': {
            const level = Math.min(3, parseInt(String(values.headingType ?? 'h1').slice(1), 10) || 1)
            const inner = String(values.text ?? '')
            return textBlocks(`<h${level}>${inner}</h${level}>`, textStyleFrom(values))
        }
        case 'button': {
            const colors = values.buttonColors ?? {}
            const inner = parseSides(values.padding)
            const label =
                chipsInText(
                    generateJSON(`<p>${String(values.text ?? '')}</p>`, buildEmailExtensions('')).content?.[0]?.content
                ) ?? []
            return [
                {
                    type: 'emailButton',
                    attrs: {
                        href: values.href?.values?.href ?? values.action?.values?.href ?? '',
                        emailStyle: compact({
                            backgroundColor: colors.backgroundColor || undefined,
                            color: colors.color || undefined,
                            fontSize: parsePx(values.fontSize),
                            fontWeight: parsePx(values.fontWeight) ?? 400,
                            borderRadius: parsePx(values.borderRadius),
                            innerPaddingX: inner?.left,
                            innerPaddingY: inner?.top,
                            textAlign: align(values.textAlign),
                            padding: parseSides(values.containerPadding),
                        }),
                    },
                    content: label,
                },
            ]
        }
        case 'image': {
            const src = values.src ?? {}
            const padding = parseSides(values.containerPadding)
            const available = contentWidth - (padding?.left ?? 0) - (padding?.right ?? 0)
            const percent =
                typeof src.maxWidth === 'string' && src.maxWidth.endsWith('%') ? parseFloat(src.maxWidth) : null
            const width =
                src.autoWidth === false && percent ? Math.round((available * percent) / 100) : parsePx(src.width)
            return [
                {
                    type: 'emailImage',
                    attrs: {
                        src: src.url ?? '',
                        alt: values.altText ?? '',
                        href: values.action?.values?.href ?? '',
                        naturalWidth: parsePx(src.width) ?? null,
                        naturalHeight: parsePx(src.height) ?? null,
                        mediaId: src.id ?? null,
                        emailStyle: compact({
                            width: width ? Math.min(width, available) : undefined,
                            textAlign: align(values.textAlign),
                            padding,
                        }),
                    },
                },
            ]
        }
        case 'divider': {
            const border = values.border ?? {}
            return [
                {
                    type: 'horizontalRule',
                    attrs: {
                        emailStyle: compact({
                            borderColor: border.borderTopColor || undefined,
                            lineWidth: parsePx(border.borderTopWidth),
                            width: parsePx(values.width),
                            textAlign: align(values.textAlign),
                            padding: parseSides(values.containerPadding),
                        }),
                    },
                },
            ]
        }
        case 'html':
            return [
                {
                    type: 'emailHtml',
                    attrs: {
                        html: String(values.html ?? ''),
                        emailStyle: compact({ padding: parseSides(values.containerPadding) }),
                    },
                },
            ]
        case 'social':
            return [
                {
                    type: 'emailHtml',
                    attrs: {
                        html: socialIconsHtml(values),
                        emailStyle: compact({ padding: parseSides(values.containerPadding) }),
                    },
                },
            ]
        case 'custom':
            if (content.slug === 'unsubscribe_link') {
                return textBlocks(String(values.unsubscribe_link_content ?? ''), textStyleFrom(values))
            }
            unsupported.add(`the custom block ${String(content.slug ?? '')}`.trim())
            return []
        default:
            unsupported.add(UNSUPPORTED_CONTENT[content.type] ?? `${String(content.type)} blocks`)
            return []
    }
}

/**
 * Builds a document from an old-editor design. Anything the new editor can't show faithfully is reported instead of
 * being dropped, and the email then stays on the old editor. Nothing is saved until a person accepts the result.
 */
export function unlayerToEmailDocument(design: Record<string, any> | null | undefined): EmailDocumentConversion {
    const body = design?.body
    if (!body || !Array.isArray(body.rows)) {
        return { document: null, unsupported: ['a design this editor can’t read'] }
    }
    const unsupported = new Set<string>()
    const bodyValues = body.values ?? {}
    const rows: any[] = [...(body.headers ?? []), ...body.rows, ...(body.footers ?? [])]
    const bodyWidth = parsePx(bodyValues.contentWidth) ?? 600

    const rowBackgrounds = new Set(rows.map((row) => row.values?.backgroundColor ?? ''))
    const sharedRowBackground = rowBackgrounds.size === 1 ? [...rowBackgrounds][0] : ''
    const columnBackgrounds = new Set(
        rows.flatMap((row) => (row.columns ?? []).map((column: any) => column.values?.backgroundColor ?? ''))
    )
    const sharedColumnBackground = columnBackgrounds.size === 1 ? [...columnBackgrounds][0] : ''

    const page: Partial<EmailPageStyle> = {
        backgroundColor: sharedRowBackground || bodyValues.backgroundColor || '#ffffff',
        bodyBackgroundColor: sharedColumnBackground || bodyValues.backgroundColor || '#ffffff',
        bodyWidth,
        bodyPadding: { top: 0, right: 0, bottom: 0, left: 0 },
        align: align(bodyValues.contentAlign) ?? 'center',
        ...(bodyValues.fontFamily?.value ? { fontFamily: bodyValues.fontFamily.value } : {}),
        ...(bodyValues.textColor ? { textColor: bodyValues.textColor } : {}),
        ...(bodyValues.linkStyle?.linkColor ? { linkColor: bodyValues.linkStyle.linkColor } : {}),
    }

    const content: JSONContent[] = []
    for (const row of rows) {
        const rowValues = row.values ?? {}
        if (rowValues.displayCondition) {
            unsupported.add('rows shown on a condition')
        }
        if (rowValues.backgroundImage?.url) {
            unsupported.add('background images')
        }
        if (rowValues.hideDesktop || rowValues.hideMobile) {
            unsupported.add('rows hidden on some screen sizes')
        }
        const cells: number[] = row.cells ?? []
        const columns: any[] = row.columns ?? []
        const totalCells = cells.reduce((total, cell) => total + cell, 0) || columns.length || 1
        const rowPadding = parseSides(rowValues.padding)
        const rowHasPadding = rowPadding && (rowPadding.top || rowPadding.right || rowPadding.bottom || rowPadding.left)
        const sectionBackground =
            (rowValues.backgroundColor && rowValues.backgroundColor !== page.backgroundColor
                ? rowValues.backgroundColor
                : '') ||
            rowValues.columnsBackgroundColor ||
            ''

        const converted = columns.map((column, index) => {
            const width = (bodyWidth * (cells[index] ?? 1)) / totalCells
            const blocks = (column.contents ?? []).flatMap((item: any) => convertContent(item, width, unsupported))
            const background = column.values?.backgroundColor
            const padding = parseSides(column.values?.padding)
            const hasPadding = padding && (padding.top || padding.right || padding.bottom || padding.left)
            return {
                blocks,
                style: compact({
                    backgroundColor: background && background !== page.bodyBackgroundColor ? background : undefined,
                    padding: hasPadding ? padding : undefined,
                    borderRadius: parsePx(column.values?.borderRadius) || undefined,
                }),
                ratio: cells[index] ?? 1,
            }
        })

        const plain = converted.length === 1 && !converted[0].style && !sectionBackground && !rowHasPadding
        if (plain) {
            content.push(...converted[0].blocks)
            continue
        }
        content.push({
            type: 'emailColumns',
            attrs: {
                emailStyle: compact({
                    backgroundColor: sectionBackground || undefined,
                    padding: rowHasPadding ? rowPadding : undefined,
                }),
            },
            content: converted.map((column) => ({
                type: 'emailColumn',
                attrs: { ratio: column.ratio, emailStyle: column.style },
                content: column.blocks.length ? column.blocks : [{ type: 'paragraph' }],
            })),
        })
    }

    if (unsupported.size) {
        return { document: null, unsupported: [...unsupported] }
    }
    return {
        document: {
            version: EMAIL_DOCUMENT_VERSION,
            doc: { type: 'doc', attrs: { page }, content: content.length ? content : [{ type: 'paragraph' }] },
        },
        unsupported: [],
    }
}
