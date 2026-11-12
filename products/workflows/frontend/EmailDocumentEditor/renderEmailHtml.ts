import type { JSONContent } from '@tiptap/core'

import {
    EmailBlockStyle,
    EmailPageStyle,
    EmailSides,
    emailFontUrls,
    isEmailDocEmpty,
    resolvePageStyle,
} from './emailDocument'

const LIQUID_SEGMENT = /(\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\})/g
const LIQUID_TAG = /\{%[\s\S]*?%\}/g
const LIQUID_TAGS_BETWEEN_ROWS = /(<\/tr>|<table\b[^>]*>)\s*(?:\{%[\s\S]*?%\}\s*)+(?=<tr\b|<\/table>)/g
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

function isOnlyLiquidTags(text: string): boolean {
    return text.trim().startsWith('{%') && text.replace(LIQUID_TAG, '').trim() === ''
}

export function isFullHtmlDocument(html: string): boolean {
    return FULL_HTML_DOCUMENT.test(html)
}

/** Text between table rows gets moved out of the table by a browser, so a preview leaves out what Liquid would remove. */
export function withoutLiquidBetweenRows(html: string): string {
    return html.replace(LIQUID_TAGS_BETWEEN_ROWS, '$1')
}

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

function safeCssValue(value: unknown): string {
    return String(value).replace(/[;"<>{}]/g, '')
}

function withLinkStyle(ctx: RenderContext, style: EmailBlockStyle): RenderContext {
    return {
        ...ctx,
        linkUnderline: style.linkUnderline ?? ctx.linkUnderline,
        page: style.linkColor ? { ...ctx.page, linkColor: style.linkColor } : ctx.page,
    }
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
    linkUnderline?: boolean
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
                return `<code style="font-family:'Courier New',Courier,monospace;color:#111111;background-color:#f2f2f2;padding:1px 4px;border-radius:3px">${inner}</code>`
            case 'textStyle': {
                const style = css({
                    color: safeColor(mark.attrs?.color),
                    'font-size': mark.attrs?.fontSize ? `${px(mark.attrs.fontSize)}px` : undefined,
                    'font-family': mark.attrs?.fontFamily ? safeFont(String(mark.attrs.fontFamily)) : undefined,
                    'letter-spacing': mark.attrs?.letterSpacing ? safeCssValue(mark.attrs.letterSpacing) : undefined,
                    'line-height': mark.attrs?.lineHeight ? safeCssValue(mark.attrs.lineHeight) : undefined,
                    'background-color': safeColor(mark.attrs?.highlight),
                    'text-transform': mark.attrs?.textTransform ? safeCssValue(mark.attrs.textTransform) : undefined,
                })
                return style ? `<span style="${style}">${inner}</span>` : inner
            }
            case 'link': {
                const href = safeEmailLink(mark.attrs?.href)
                if (!href) {
                    return inner
                }
                const color =
                    mark.attrs?.color ?? (node.marks ?? []).find((other) => other.type === 'textStyle')?.attrs?.color
                const underline = mark.attrs?.underline !== false && ctx.linkUnderline !== false
                return `<a href="${escapeAttribute(href)}" target="_blank" style="color:${safeColor(color, ctx.page.linkColor)};text-decoration:${underline ? 'underline' : 'none'}">${inner}</a>`
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
        'font-family': safeFont(style.fontFamily ?? ctx.page.fontFamily),
        'font-weight': style.fontWeight,
        'font-size': `${px(style.fontSize, fontSize)}px`,
        'line-height': `${px(style.lineHeight, ctx.page.lineHeight)}%`,
        color: safeColor(style.color, ctx.page.textColor),
        'letter-spacing': style.letterSpacing ? `${px(style.letterSpacing)}px` : undefined,
        'text-transform': style.uppercase ? 'uppercase' : undefined,
        // A table grows to fit its longest word, so a long link would otherwise widen the whole email.
        'overflow-wrap': 'anywhere',
        'word-break': 'break-word',
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
            return `<li style="margin:0 0 ${px(style.listItemGap, 4)}px 0">${parts.join('')}</li>`
        })
        .join('')
    // Outlook on Windows ignores list padding and then has no room left to draw the bullets or numbers.
    const listCss = css({
        margin: `0 0 0 ${px(style.listIndent, 24)}px`,
        padding: 0,
        ...textProperties(style, ctx, ctx.page.fontSize),
    })
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
    const label = renderInline(node.content, { ...ctx, page: { ...ctx.page, linkColor: color } })
    if (!label) {
        return ''
    }
    const fullWidth = style.buttonWidth ? Math.min(px(style.buttonWidth), 100) : null
    const linkCss = css({
        display: fullWidth ? 'block' : 'inline-block',
        'text-align': 'center',
        padding: `${paddingY}px ${paddingX}px`,
        ...textProperties(
            { ...style, color, fontWeight: px(style.fontWeight, 600), lineHeight: style.lineHeight ?? 120 },
            ctx,
            ctx.page.fontSize
        ),
        'text-decoration': 'none',
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
    const buttonFontSize = px(style.fontSize, ctx.page.fontSize)
    const labelText = textFromNodes(node.content)
    // Word ignores border-radius, and only a VML shape gets rounded corners there. A shape can't size itself to its
    // label, so a label that depends on a variable stays square rather than risk being cut off.
    const hasVariable = (node.content ?? []).some((child) => child.type === 'variable') || labelText.includes('{')
    const outlookButton =
        radius > 0 && href && !hasVariable
            ? (() => {
                  const height = Math.round(buttonFontSize * ((style.lineHeight ?? 120) / 100) + paddingY * 2)
                  const width = fullWidth
                      ? Math.round((ctx.contentWidth * fullWidth) / 100)
                      : Math.ceil(labelText.length * buttonFontSize * 0.62) + paddingX * 2
                  const arc = Math.min(50, Math.round((radius / Math.min(height, width)) * 100))
                  return `<!--[if mso]><v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="${escapeAttribute(href)}" style="height:${height}px;v-text-anchor:middle;width:${width}px;" arcsize="${arc}%" ${style.borderWidth ? `strokecolor="${safeColor(style.borderColor, background)}" strokeweight="${px(style.borderWidth)}px"` : 'stroke="f"'} fillcolor="${background}"><w:anchorlock/><center style="color:${color};font-family:${safeFont(style.fontFamily ?? ctx.page.fontFamily).replace(/'/g, '')};font-size:${buttonFontSize}px;font-weight:${px(style.fontWeight, 600)}">${escapeText(labelText)}</center></v:roundrect><![endif]-->`
              })()
            : ''
    const tableWidth = fullWidth ? ` width="${fullWidth}%"` : ''
    const button = `<table role="presentation"${tableWidth} border="0" cellpadding="0" cellspacing="0" style="${fullWidth ? `width:${fullWidth}%;` : ''}display:inline-table;border-collapse:separate"><tr><td align="center" bgcolor="${background}" style="${cellCss}">${anchor}</td></tr></table>`
    return blockCell(
        { textAlign: style.textAlign, padding: style.padding ?? { ...DEFAULT_BLOCK_SIDES, top: 12, bottom: 12 } },
        outlookButton ? `${outlookButton}<!--[if !mso]><!-->${button}<!--<![endif]-->` : button
    )
}

function renderColumns(node: JSONContent, ctx: RenderContext): string {
    const style = styleOf(node)
    const padding = style.padding ?? NO_SIDES
    const columns = node.content ?? []
    const available = Math.max(1, ctx.contentWidth - px(padding.left) - px(padding.right))
    const totalRatio = columns.reduce((total, column) => total + (px(column.attrs?.ratio, 1) || 1), 0) || 1
    const gap = columns.length > 1 ? px(style.columnGap, COLUMN_GAP) : 0
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
                'line-height': ctx.page.oldEditorStyles ? 'normal' : `${px(ctx.page.lineHeight)}%`,
                'background-color': background,
                'box-sizing': 'border-box',
                padding: sides(columnPadding),
                border: columnStyle.borderWidth
                    ? `${px(columnStyle.borderWidth)}px solid ${safeColor(columnStyle.borderColor, '#e5e5e5')}`
                    : undefined,
                'border-radius': columnStyle.borderRadius ? `${px(columnStyle.borderRadius)}px` : undefined,
            })
            // Outlook ignores a div's background and padding, so its cell carries them.
            const msoCell = `<td width="${width}" valign="top"${background ? ` bgcolor="${background}"` : ''} style="padding:${sides(columnPadding)}">`
            const before =
                index === 0
                    ? `<!--[if mso]><table role="presentation" width="${available}" cellpadding="0" cellspacing="0" border="0"><tr>${msoCell}<![endif]-->`
                    : `<!--[if mso]></td>${msoCell}<![endif]-->`
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

/** The element inside a text block's cell, which the old editor's text blocks hold as they are. */
function textBlockElement(node: JSONContent, ctx: RenderContext): string | null {
    const style = styleOf(node)
    switch (node.type) {
        case 'paragraph': {
            const inner = renderInline(node.content, ctx) || '&nbsp;'
            const paragraphCss = css({ margin: 0, ...textProperties(style, ctx, ctx.page.fontSize) })
            return `<p style="${paragraphCss}">${inner}</p>`
        }
        case 'heading': {
            const level = Math.min(3, Math.max(1, Number(node.attrs?.level) || 1))
            const headingCss = css({
                margin: 0,
                ...textProperties({ lineHeight: 125, fontWeight: 700, ...style }, ctx, headingSize(level, ctx.page)),
            })
            return `<h${level} style="${headingCss}">${renderInline(node.content, ctx) || '&nbsp;'}</h${level}>`
        }
        case 'bulletList':
        case 'orderedList':
            return renderList(node, ctx)
        case 'blockquote': {
            const children = node.content ?? []
            const inner = children
                .map((child, index) =>
                    child.type === 'paragraph'
                        ? `<p style="${css({ margin: index === children.length - 1 ? 0 : '0 0 8px 0', ...textProperties(style, ctx, ctx.page.fontSize) })}">${renderInline(child.content, ctx) || '&nbsp;'}</p>`
                        : renderBlockTable([child], ctx)
                )
                .join('')
            return `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td style="border-left:3px solid ${safeColor(style.borderColor, '#d0d0d0')};padding:0 0 0 12px">${inner}</td></tr></table>`
        }
        default:
            return null
    }
}

function renderBlock(node: JSONContent, parentCtx: RenderContext): string {
    const style = styleOf(node)
    const ctx = withLinkStyle(parentCtx, style)
    switch (node.type) {
        case 'paragraph': {
            const text = textFromNodes(node.content)
            // A Liquid tag alone on its line (`{% for %}`, `{% endif %}`) is structure, and it must not leave a gap.
            if (isOnlyLiquidTags(text)) {
                return text.trim()
            }
            return blockCell(style, textBlockElement(node, ctx) ?? '')
        }
        case 'heading':
        case 'bulletList':
        case 'orderedList':
        case 'blockquote':
            return blockCell(style, textBlockElement(node, ctx) ?? '')
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
            const background = safeColor(node.attrs?.backgroundColor, '')
            return `<tr><td height="${height}"${background ? ` bgcolor="${background}"` : ''} style="height:${height}px;font-size:1px;line-height:1px${background ? `;background-color:${background}` : ''}">&nbsp;</td></tr>`
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
                `<div style="${style.inheritText ? `font-family:${safeFont(ctx.page.fontFamily)};overflow-wrap:break-word;word-break:break-word` : css(textProperties({}, ctx, ctx.page.fontSize))}">${htmlBlockFragment(String(node.attrs?.html ?? ''))}</div>`,
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
export function withoutTrailingEmptyParagraphs(nodes: JSONContent[]): JSONContent[] {
    let end = nodes.length
    while (end > 0 && nodes[end - 1].type === 'paragraph' && !nodes[end - 1].content?.length) {
        end -= 1
    }
    return nodes.slice(0, end)
}

/** The page-wide rules every old-editor email carries, so its custom HTML lays out the way it did. */
export function oldEditorCss(page: EmailPageStyle): string {
    return `table, td, tr { border-collapse: collapse; vertical-align: top; }
p { margin: 0; }
* { line-height: inherit; }
table, td { color: ${safeColor(page.textColor, '#000000')}; }`
}

function responsiveCss(page: EmailPageStyle): string {
    const breakpoint = page.bodyWidth + 20
    const custom = page.globalCss.replace(/<\/?style/gi, '')
    return `
body { margin: 0; padding: 0; }
body, table, td, a { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
img { -ms-interpolation-mode: bicubic; }
a { color: ${safeColor(page.linkColor, '#1d4aff')}; }
@media only screen and (max-width: ${breakpoint}px) {
  .ph-body { width: 100% !important; }
  .ph-col { max-width: 100% !important; }
  .ph-col-gap { padding-left: 0 !important; padding-right: 0 !important; }
}
${page.oldEditorStyles ? oldEditorCss(page) : ''}
${custom}`.trim()
}

function oldEditorContext(page: EmailPageStyle, contentWidth: number, style: EmailBlockStyle): RenderContext {
    return withLinkStyle({ page, contentWidth }, style)
}

/**
 * A block as the old editor shows it: a text block's element goes in one of its text blocks, and anything else is
 * markup for one of its HTML blocks. A Liquid tag alone on its line stays bare, as it is when sent.
 */
export function oldEditorBlockHtml(
    node: JSONContent,
    page: EmailPageStyle,
    contentWidth: number
): { kind: 'text' | 'html'; html: string } {
    const ctx = oldEditorContext(page, contentWidth, styleOf(node))
    if (node.type === 'paragraph' && isOnlyLiquidTags(textFromNodes(node.content))) {
        return { kind: 'html', html: textFromNodes(node.content).trim() }
    }
    const text = textBlockElement(node, ctx)
    return text !== null ? { kind: 'text', html: text } : { kind: 'html', html: renderBlockTable([node], ctx) }
}

/** A button's label as markup, with its variables written out. */
export function oldEditorInlineHtml(nodes: JSONContent[] | undefined, page: EmailPageStyle): string {
    return renderInline(nodes, { page, contentWidth: page.bodyWidth })
}

/** The email as it is sent. An empty document renders to nothing, so "no content" checks keep working. */
export function renderEmailHtml(doc: JSONContent): string {
    if (isEmailDocEmpty(doc)) {
        return ''
    }
    const nodes = withoutTrailingEmptyParagraphs(doc.content ?? [])

    // An email that is only one HTML block is the author's own document: it goes out exactly as written.
    if (
        nodes.length === 1 &&
        nodes[0].type === 'emailHtml' &&
        FULL_HTML_DOCUMENT.test(nodes[0].attrs?.html ?? '') &&
        !doc.attrs?.page?.wrapFullHtml
    ) {
        // The API trims html when it's saved, and the stored copy in the design has to keep matching it.
        return String(nodes[0].attrs?.html).trim()
    }

    const page = resolvePageStyle(doc.attrs?.page)
    const padding = page.bodyPadding
    const bodyWidth = px(page.bodyWidth, 600) || 600
    const ctx: RenderContext = {
        page,
        // A border is drawn inside the body's width, so it takes room from the content too.
        contentWidth: Math.max(1, bodyWidth - px(padding.left) - px(padding.right) - px(page.bodyBorderWidth) * 2),
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
    // Declaring light keeps a mail app from recoloring the email in dark mode. Old-editor emails never declared it, so
    // on a converted one that would be a change people notice.
    const colorSchemeMeta = page.oldEditorStyles
        ? ''
        : '<meta name="color-scheme" content="light" />\n<meta name="supported-color-schemes" content="light" />\n'
    // Outlook on Windows falls back to Times New Roman for a font it has to download, instead of the next one listed.
    const fontUrls = emailFontUrls(doc)
    const fontLinks = fontUrls.length
        ? `<!--[if !mso]><!-->\n${fontUrls.map((url) => `<link rel="stylesheet" href="${escapeAttribute(url)}" />\n`).join('')}<!--<![endif]-->\n`
        : ''
    const previewText = page.previewText
        ? `<div style="display:none;max-height:0;max-width:0;overflow:hidden;opacity:0;font-size:1px;line-height:1px;mso-hide:all">${escapeText(page.previewText)}</div>\n`
        : ''
    return `<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="x-apple-disable-message-reformatting" />
${colorSchemeMeta}${fontLinks}<!--[if mso]><xml><o:OfficeDocumentSettings><o:AllowPNG/><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml><![endif]-->
<style type="text/css">
${responsiveCss(page)}
</style>
</head>
<body style="margin:0;padding:0;background-color:${pageBackground}">
${previewText}<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="${pageBackground}" style="background-color:${pageBackground}"><tr><td align="${page.align}" style="padding:${px(page.padding)}px">
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
            const label = inlineText(node.content)
            return href && label ? `${label}: ${href}` : label
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
