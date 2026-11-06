import type { JSONContent } from '@tiptap/core'

import { EmailBlockStyle, EmailPageStyle, EmailSides, isEmailDocEmpty, resolvePageStyle } from './emailDocument'

const LIQUID_SEGMENT = /(\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\})/g
const ONLY_LIQUID_TAG = /^\s*\{%[\s\S]*%\}\s*$/
const FULL_HTML_DOCUMENT = /<\s*(html|body|!doctype)\b/i
const SAFE_LINK = /^(https?:|mailto:|tel:|#|\/)/i
const SAFE_IMAGE = /^(https?:|\/)/i
const STARTS_WITH_LIQUID = /^\s*\{[{%]/
const SAFE_COLOR = /^(#[0-9a-f]{3,8}|rgba?\([\d\s.,%]+\)|[a-z]+)$/i

const COLUMN_GAP = 16
const DEFAULT_BLOCK_SIDES: EmailSides = { top: 8, right: 0, bottom: 8, left: 0 }
const NO_SIDES: EmailSides = { top: 0, right: 0, bottom: 0, left: 0 }
const BUTTON_PADDING_X = 24
const BUTTON_PADDING_Y = 12

function escapeOutsideLiquid(text: string, escape: (segment: string) => string): string {
    return text
        .split(LIQUID_SEGMENT)
        .map((segment, index) => (index % 2 === 1 ? segment : escape(segment)))
        .join('')
}

function escapeText(text: string): string {
    return escapeOutsideLiquid(text, (segment) =>
        segment.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    )
}

function escapeAttribute(text: string): string {
    // A double quote ends the attribute even inside a Liquid tag. The send path decodes entities in Liquid tags.
    return escapeOutsideLiquid(text, (segment) =>
        segment.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    ).replace(/"/g, '&quot;')
}

export function safeEmailLink(url: unknown): string {
    if (typeof url !== 'string') {
        return ''
    }
    const trimmed = url.trim()
    if (STARTS_WITH_LIQUID.test(trimmed) || SAFE_LINK.test(trimmed)) {
        return trimmed
    }
    // A bare domain is what people type. Anything with its own scheme (javascript:, data:) isn't allowed.
    return /^[^\s:/]+\.[^\s:]+/.test(trimmed) ? `https://${trimmed}` : ''
}

function safeImage(url: unknown): string {
    if (typeof url !== 'string') {
        return ''
    }
    const trimmed = url.trim()
    return STARTS_WITH_LIQUID.test(trimmed) || SAFE_IMAGE.test(trimmed) ? trimmed : ''
}

function safeColor(color: unknown, fallback = ''): string {
    return typeof color === 'string' && SAFE_COLOR.test(color.trim()) ? color.trim() : fallback
}

function safeFont(font: string): string {
    return font.replace(/[;"<>{}]/g, '')
}

function px(value: unknown, fallback = 0): number {
    const number = typeof value === 'number' ? value : Number(value)
    return Number.isFinite(number) ? Math.max(0, Math.round(number * 100) / 100) : fallback
}

function sides(value: EmailSides): string {
    return `${px(value.top)}px ${px(value.right)}px ${px(value.bottom)}px ${px(value.left)}px`
}

function css(properties: Record<string, string | number | undefined | null | false>): string {
    return Object.entries(properties)
        .filter(([, value]) => value !== undefined && value !== null && value !== false && value !== '')
        .map(([key, value]) => `${key}:${value}`)
        .join(';')
}

function styleOf(node: JSONContent): EmailBlockStyle {
    return (node.attrs?.emailStyle as EmailBlockStyle | null | undefined) ?? {}
}

interface RenderContext {
    page: EmailPageStyle
    contentWidth: number
}

function textFromNodes(nodes: JSONContent[] | undefined): string {
    return (nodes ?? []).map((node) => node.text ?? textFromNodes(node.content)).join('')
}

function renderVariable(node: JSONContent): string {
    const expression = String(node.attrs?.expression ?? '')
        .replace(/\}\}/g, '')
        .trim()
    if (!expression) {
        return ''
    }
    const fallback = node.attrs?.fallback
    if (typeof fallback === 'string' && fallback !== '') {
        return `{{ ${expression} | default: '${fallback.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}' }}`
    }
    return `{{ ${expression} }}`
}

function wrapMarks(html: string, node: JSONContent, ctx: RenderContext): string {
    return (node.marks ?? []).reduceRight((inner, mark) => {
        switch (mark.type) {
            case 'bold':
                return `<strong>${inner}</strong>`
            case 'italic':
                return `<em>${inner}</em>`
            case 'underline':
                return `<u>${inner}</u>`
            case 'strike':
                return `<s>${inner}</s>`
            case 'code':
                return `<code style="font-family:'Courier New',Courier,monospace;background-color:#f2f2f2;padding:1px 4px;border-radius:3px">${inner}</code>`
            case 'textStyle': {
                const style = css({
                    color: safeColor(mark.attrs?.color),
                    'font-size': mark.attrs?.fontSize ? `${px(mark.attrs.fontSize)}px` : undefined,
                    'font-family': mark.attrs?.fontFamily ? safeFont(String(mark.attrs.fontFamily)) : undefined,
                })
                return style ? `<span style="${style}">${inner}</span>` : inner
            }
            case 'link': {
                const href = safeEmailLink(mark.attrs?.href)
                if (!href) {
                    return inner
                }
                const color = (node.marks ?? []).find((other) => other.type === 'textStyle')?.attrs?.color
                return `<a href="${escapeAttribute(href)}" target="_blank" style="color:${safeColor(color, ctx.page.linkColor)};text-decoration:underline">${inner}</a>`
            }
            default:
                return inner
        }
    }, html)
}

function renderInline(nodes: JSONContent[] | undefined, ctx: RenderContext): string {
    return (nodes ?? [])
        .map((node) => {
            switch (node.type) {
                case 'text':
                    return wrapMarks(escapeText(node.text ?? ''), node, ctx)
                case 'variable':
                    return wrapMarks(renderVariable(node), node, ctx)
                case 'hardBreak':
                    return '<br />'
                default:
                    return ''
            }
        })
        .join('')
}

function textProperties(style: EmailBlockStyle, ctx: RenderContext, fontSize: number): Record<string, any> {
    return {
        'font-family': safeFont(ctx.page.fontFamily),
        'font-size': `${px(style.fontSize, fontSize)}px`,
        'line-height': `${px(style.lineHeight, ctx.page.lineHeight)}%`,
        color: safeColor(style.color, ctx.page.textColor),
        'letter-spacing': style.letterSpacing ? `${px(style.letterSpacing)}px` : undefined,
        'text-transform': style.uppercase ? 'uppercase' : undefined,
    }
}

function blockCell(style: EmailBlockStyle, inner: string, defaultPadding: EmailSides = DEFAULT_BLOCK_SIDES): string {
    const align = style.textAlign ?? 'left'
    const background = safeColor(style.backgroundColor)
    const attributes = [`align="${align}"`, background ? `bgcolor="${background}"` : ''].filter(Boolean).join(' ')
    const cellCss = css({
        padding: sides(style.padding ?? defaultPadding),
        'text-align': align,
        'background-color': background,
        'border-radius': style.borderRadius ? `${px(style.borderRadius)}px` : undefined,
        border: style.borderWidth
            ? `${px(style.borderWidth)}px solid ${safeColor(style.borderColor, '#e5e5e5')}`
            : undefined,
    })
    return `<tr><td ${attributes} style="${cellCss}">${inner}</td></tr>`
}

function renderList(node: JSONContent, ctx: RenderContext): string {
    const tag = node.type === 'orderedList' ? 'ol' : 'ul'
    const style = styleOf(node)
    const items = (node.content ?? [])
        .map((item) => {
            const parts = (item.content ?? []).map((child) =>
                child.type === 'bulletList' || child.type === 'orderedList'
                    ? renderList(child, ctx)
                    : renderInline(child.content, ctx)
            )
            return `<li style="margin:0 0 4px 0">${parts.join('')}</li>`
        })
        .join('')
    const listCss = css({ margin: 0, 'padding-left': '24px', ...textProperties(style, ctx, ctx.page.fontSize) })
    return `<${tag} style="${listCss}">${items}</${tag}>`
}

function headingSize(level: number, page: EmailPageStyle): number {
    return level === 1 ? page.h1Size : level === 2 ? page.h2Size : page.h3Size
}

function renderImage(node: JSONContent, ctx: RenderContext): string {
    const style = styleOf(node)
    const padding = style.padding ?? NO_SIDES
    const src = safeImage(node.attrs?.src)
    if (!src) {
        return ''
    }
    const available = Math.max(1, ctx.contentWidth - px(padding.left) - px(padding.right))
    const width = Math.min(px(style.width ?? node.attrs?.naturalWidth, available) || available, available)
    const align = style.textAlign ?? 'left'
    const imageCss = css({
        display: 'block',
        width: '100%',
        'max-width': `${width}px`,
        height: 'auto',
        border: 0,
        outline: 'none',
        'text-decoration': 'none',
        'border-radius': style.borderRadius ? `${px(style.borderRadius)}px` : undefined,
        'margin-left': align === 'left' ? undefined : 'auto',
        'margin-right': align === 'right' ? undefined : align === 'center' ? 'auto' : undefined,
    })
    const image = `<img src="${escapeAttribute(src)}" alt="${escapeAttribute(String(node.attrs?.alt ?? ''))}" width="${width}" style="${imageCss}" />`
    const href = safeEmailLink(node.attrs?.href)
    const inner = href ? `<a href="${escapeAttribute(href)}" target="_blank">${image}</a>` : image
    return blockCell({ ...style, borderRadius: undefined, borderWidth: undefined }, inner, NO_SIDES)
}

function renderButton(node: JSONContent, ctx: RenderContext): string {
    const style = styleOf(node)
    const href = safeEmailLink(node.attrs?.href)
    const background = safeColor(style.backgroundColor, ctx.page.buttonBackgroundColor)
    const color = safeColor(style.color, ctx.page.buttonTextColor)
    const radius = px(style.borderRadius, ctx.page.buttonBorderRadius)
    const paddingX = px(style.innerPaddingX, BUTTON_PADDING_X)
    const paddingY = px(style.innerPaddingY, BUTTON_PADDING_Y)
    const border = style.borderWidth
        ? `${px(style.borderWidth)}px solid ${safeColor(style.borderColor, background)}`
        : undefined
    const label = renderInline(node.content, { ...ctx, page: { ...ctx.page, linkColor: color } }) || '&nbsp;'
    const linkCss = css({
        display: 'inline-block',
        padding: `${paddingY}px ${paddingX}px`,
        ...textProperties({ ...style, color }, ctx, ctx.page.fontSize),
        'font-weight': px(style.fontWeight, 600),
        'text-decoration': 'none',
        'line-height': '120%',
        'border-radius': `${radius}px`,
    })
    // The cell carries the color and padding for Outlook, which ignores padding on a link and any corner radius.
    const cellCss = css({
        'background-color': background,
        'border-radius': `${radius}px`,
        'mso-padding-alt': `${paddingY}px ${paddingX}px`,
        border,
    })
    const anchor = href
        ? `<a href="${escapeAttribute(href)}" target="_blank" style="${linkCss}">${label}</a>`
        : `<span style="${linkCss}">${label}</span>`
    const button = `<table role="presentation" border="0" cellpadding="0" cellspacing="0" style="display:inline-table;border-collapse:separate"><tr><td align="center" bgcolor="${background}" style="${cellCss}">${anchor}</td></tr></table>`
    return blockCell(
        { textAlign: style.textAlign, padding: style.padding ?? { ...DEFAULT_BLOCK_SIDES, top: 12, bottom: 12 } },
        button
    )
}

function renderColumns(node: JSONContent, ctx: RenderContext): string {
    const style = styleOf(node)
    const padding = style.padding ?? NO_SIDES
    const columns = node.content ?? []
    const available = Math.max(1, ctx.contentWidth - px(padding.left) - px(padding.right))
    const totalRatio = columns.reduce((total, column) => total + (px(column.attrs?.ratio, 1) || 1), 0) || 1
    const gap = columns.length > 1 ? COLUMN_GAP : 0
    const widths = columns.map((column) => Math.floor((available * (px(column.attrs?.ratio, 1) || 1)) / totalRatio))
    // Each column is an inline-block capped at its width, so columns wrap into a stack on a narrow screen without
    // needing a media query (Gmail apps drop those). Outlook ignores inline-block, so it gets a real table instead.
    const cells = columns
        .map((column, index) => {
            const columnStyle = styleOf(column)
            const width = widths[index]
            const columnPadding = columnStyle.padding ?? {
                ...NO_SIDES,
                left: index === 0 ? 0 : gap / 2,
                right: index === columns.length - 1 ? 0 : gap / 2,
            }
            const innerWidth = Math.max(1, width - px(columnPadding.left) - px(columnPadding.right))
            const inner = renderBlockTable(column.content, { ...ctx, contentWidth: innerWidth })
            const background = safeColor(columnStyle.backgroundColor)
            const divCss = css({
                display: 'inline-block',
                width: '100%',
                'max-width': `${width}px`,
                'vertical-align': 'top',
                // The cell around the columns zeroes these to close the gaps between inline blocks.
                'font-size': `${ctx.page.fontSize}px`,
                'line-height': `${px(ctx.page.lineHeight)}%`,
                'background-color': background,
                'box-sizing': 'border-box',
                padding: sides(columnPadding),
            })
            const before =
                index === 0
                    ? `<!--[if mso]><table role="presentation" width="${available}" cellpadding="0" cellspacing="0" border="0"><tr><td width="${width}" valign="top"><![endif]-->`
                    : `<!--[if mso]></td><td width="${width}" valign="top"><![endif]-->`
            const className = columnStyle.padding ? 'ph-col' : 'ph-col ph-col-gap'
            return `${before}<div class="${className}" style="${divCss}">${inner}</div>`
        })
        .join('')
    const outer = `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td style="font-size:0;line-height:0;text-align:left">${cells}<!--[if mso]></td></tr></table><![endif]--></td></tr></table>`
    return blockCell({ ...style, padding }, outer, NO_SIDES)
}

/** A whole document can't sit inside the email's table, so next to other blocks only its styles and body are used. */
function htmlBlockFragment(html: string): string {
    if (!FULL_HTML_DOCUMENT.test(html)) {
        return html
    }
    const doc = new DOMParser().parseFromString(html, 'text/html')
    const styles = Array.from(doc.querySelectorAll('style'))
        .map((style) => style.outerHTML)
        .join('')
    doc.body.querySelectorAll('style').forEach((style) => style.remove())
    return styles + doc.body.innerHTML
}

function renderBlock(node: JSONContent, ctx: RenderContext): string {
    const style = styleOf(node)
    switch (node.type) {
        case 'paragraph': {
            const text = textFromNodes(node.content)
            // A Liquid tag alone on its line (`{% for %}`, `{% endif %}`) is structure, and it must not leave a gap.
            if (ONLY_LIQUID_TAG.test(text)) {
                return text.trim()
            }
            const inner = renderInline(node.content, ctx) || '&nbsp;'
            const paragraphCss = css({ margin: 0, ...textProperties(style, ctx, ctx.page.fontSize) })
            return blockCell(style, `<p style="${paragraphCss}">${inner}</p>`)
        }
        case 'heading': {
            const level = Math.min(3, Math.max(1, Number(node.attrs?.level) || 1))
            const headingCss = css({
                margin: 0,
                'font-weight': 700,
                ...textProperties({ lineHeight: 125, ...style }, ctx, headingSize(level, ctx.page)),
            })
            return blockCell(
                style,
                `<h${level} style="${headingCss}">${renderInline(node.content, ctx) || '&nbsp;'}</h${level}>`
            )
        }
        case 'bulletList':
        case 'orderedList':
            return blockCell(style, renderList(node, ctx))
        case 'blockquote': {
            const inner = (node.content ?? [])
                .map((child) =>
                    child.type === 'paragraph'
                        ? `<p style="${css({ margin: '0 0 8px 0', ...textProperties(style, ctx, ctx.page.fontSize) })}">${renderInline(child.content, ctx) || '&nbsp;'}</p>`
                        : renderBlockTable([child], ctx)
                )
                .join('')
            return blockCell(
                style,
                `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td style="border-left:3px solid ${safeColor(style.borderColor, '#d0d0d0')};padding:0 0 0 12px">${inner}</td></tr></table>`
            )
        }
        case 'horizontalRule': {
            const width = px(style.width, 100) || 100
            const line = `<table role="presentation" width="${Math.min(width, 100)}%" align="${style.textAlign ?? 'center'}" cellpadding="0" cellspacing="0" border="0"><tr><td style="border-top:${px(style.lineWidth, 1) || 1}px solid ${safeColor(style.borderColor, '#dddddd')};font-size:1px;line-height:1px">&nbsp;</td></tr></table>`
            return blockCell(
                { ...style, borderColor: undefined, borderWidth: undefined, borderRadius: undefined },
                line
            )
        }
        case 'emailSpacer': {
            const height = px(node.attrs?.height, 24)
            return `<tr><td height="${height}" style="height:${height}px;font-size:1px;line-height:1px">&nbsp;</td></tr>`
        }
        case 'emailImage':
            return renderImage(node, ctx)
        case 'emailButton':
            return renderButton(node, ctx)
        case 'emailColumns':
            return renderColumns(node, ctx)
        case 'emailHtml':
            // Its own markup may not set a font, so it starts from the page's rather than from the email app's.
            return blockCell(
                style,
                `<div style="${css(textProperties({}, ctx, ctx.page.fontSize))}">${htmlBlockFragment(String(node.attrs?.html ?? ''))}</div>`,
                NO_SIDES
            )
        default:
            return ''
    }
}

function renderBlockRows(nodes: JSONContent[] | undefined, ctx: RenderContext): string {
    return (nodes ?? []).map((node) => renderBlock(node, ctx)).join('')
}

function renderBlockTable(nodes: JSONContent[] | undefined, ctx: RenderContext): string {
    return `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">${renderBlockRows(nodes, ctx)}</table>`
}

/** The editor keeps an empty paragraph at the end so there's always somewhere to type. It isn't part of the email. */
function withoutTrailingEmptyParagraphs(nodes: JSONContent[]): JSONContent[] {
    let end = nodes.length
    while (end > 0 && nodes[end - 1].type === 'paragraph' && !nodes[end - 1].content?.length) {
        end -= 1
    }
    return nodes.slice(0, end)
}

function responsiveCss(page: EmailPageStyle): string {
    const breakpoint = page.bodyWidth + 20
    const custom = page.globalCss.replace(/<\/?style/gi, '')
    return `
body, table, td, a { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
img { -ms-interpolation-mode: bicubic; }
a { color: ${safeColor(page.linkColor, '#1d4aff')}; }
@media only screen and (max-width: ${breakpoint}px) {
  .ph-body { width: 100% !important; }
  .ph-col { max-width: 100% !important; }
  .ph-col-gap { padding-left: 0 !important; padding-right: 0 !important; }
}
${custom}`.trim()
}

/** The email as it is sent. An empty document renders to nothing, so "no content" checks keep working. */
export function renderEmailHtml(doc: JSONContent): string {
    if (isEmailDocEmpty(doc)) {
        return ''
    }
    const nodes = withoutTrailingEmptyParagraphs(doc.content ?? [])

    // An email that is only one HTML block is the author's own document: it goes out exactly as written.
    if (nodes.length === 1 && nodes[0].type === 'emailHtml' && FULL_HTML_DOCUMENT.test(nodes[0].attrs?.html ?? '')) {
        return String(nodes[0].attrs?.html)
    }

    const page = resolvePageStyle(doc.attrs?.page)
    const padding = page.bodyPadding
    const bodyWidth = px(page.bodyWidth, 600) || 600
    const ctx: RenderContext = {
        page,
        contentWidth: Math.max(1, bodyWidth - px(padding.left) - px(padding.right)),
    }
    const pageBackground = safeColor(page.backgroundColor, '#ffffff')
    const bodyBackground = safeColor(page.bodyBackgroundColor, '#ffffff')
    const bodyCss = css({
        width: '100%',
        'max-width': `${bodyWidth}px`,
        'background-color': bodyBackground,
        'border-radius': page.bodyBorderRadius ? `${px(page.bodyBorderRadius)}px` : undefined,
        border: page.bodyBorderWidth
            ? `${px(page.bodyBorderWidth)}px solid ${safeColor(page.bodyBorderColor, '#e5e5e5')}`
            : undefined,
    })
    return `<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="x-apple-disable-message-reformatting" />
<meta name="color-scheme" content="light" />
<meta name="supported-color-schemes" content="light" />
<!--[if mso]><xml><o:OfficeDocumentSettings><o:AllowPNG/><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml><![endif]-->
<style type="text/css">
${responsiveCss(page)}
</style>
</head>
<body style="margin:0;padding:0;background-color:${pageBackground}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="${pageBackground}" style="background-color:${pageBackground}"><tr><td align="${page.align}" style="padding:${px(page.padding)}px">
<!--[if mso]><table role="presentation" width="${bodyWidth}" align="${page.align}" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
<table class="ph-body" role="presentation" width="100%" align="${page.align}" cellpadding="0" cellspacing="0" border="0" bgcolor="${bodyBackground}" style="${bodyCss}"><tr><td style="padding:${sides(padding)}">
${renderBlockTable(nodes, ctx)}
</td></tr></table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table>
</body>
</html>`
}

function textFromHtml(html: string): string {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    doc.querySelectorAll('style, script, head, title').forEach((element) => element.remove())
    // textContent runs neighboring blocks together, so each one gets a line of its own first.
    doc.querySelectorAll('br, p, div, tr, li, h1, h2, h3, h4, h5, h6').forEach((element) => element.after('\n'))
    doc.querySelectorAll('td').forEach((element) => element.after(' '))
    return (doc.body?.textContent ?? '')
        .replace(/[ \t]+/g, ' ')
        .replace(/ ?\n ?/g, '\n')
        .replace(/\n{2,}/g, '\n')
        .trim()
}

function inlineText(nodes: JSONContent[] | undefined): string {
    return (nodes ?? [])
        .map((node) => {
            if (node.type === 'variable') {
                return renderVariable(node)
            }
            if (node.type === 'hardBreak') {
                return '\n'
            }
            const text = node.text ?? ''
            const href = node.marks?.find((mark) => mark.type === 'link')?.attrs?.href
            return href && href !== text ? `${text} (${href})` : text
        })
        .join('')
}

function blockText(node: JSONContent): string {
    switch (node.type) {
        case 'paragraph':
        case 'heading':
            return inlineText(node.content)
        case 'bulletList':
        case 'orderedList':
            return (node.content ?? [])
                .map((item, index) => {
                    const marker = node.type === 'orderedList' ? `${index + 1}. ` : '- '
                    return marker + (item.content ?? []).map(blockText).join('\n')
                })
                .join('\n')
        case 'blockquote':
            return (node.content ?? []).map((child) => `> ${blockText(child)}`).join('\n')
        case 'horizontalRule':
            return '---'
        case 'emailImage':
            return String(node.attrs?.alt ?? '')
        case 'emailButton': {
            const href = safeEmailLink(node.attrs?.href)
            return href ? `${inlineText(node.content)}: ${href}` : inlineText(node.content)
        }
        case 'emailColumns':
            return (node.content ?? []).map(blockText).filter(Boolean).join('\n\n')
        case 'emailColumn':
            return (node.content ?? []).map(blockText).filter(Boolean).join('\n\n')
        case 'emailHtml':
            return textFromHtml(String(node.attrs?.html ?? ''))
        default:
            return ''
    }
}

export function renderEmailText(doc: JSONContent): string {
    if (isEmailDocEmpty(doc)) {
        return ''
    }
    return withoutTrailingEmptyParagraphs(doc.content ?? [])
        .map(blockText)
        .filter(Boolean)
        .join('\n\n')
}
