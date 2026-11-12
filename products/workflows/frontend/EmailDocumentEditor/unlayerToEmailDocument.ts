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
    /** What a conversion leaves out, for the person to weigh up before accepting. */
    notKept: string[]
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

function containerPadding(values: Record<string, any>): EmailSides {
    return parseSides(values.containerPadding) ?? { top: 10, right: 10, bottom: 10, left: 10 }
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
                    const match = part.match(/^\{\{(?!-)([^{}]*[^{}-])\}\}$/)
                    return match
                        ? { type: 'variable', attrs: parseLiquidOutput(match[1]), marks: node.marks }
                        : { ...node, text: part }
                })
        }
        LIQUID_OUTPUT.lastIndex = 0
        return node.content ? [{ ...node, content: chipsInText(node.content) }] : [node]
    })
}

/**
 * Where an old-editor link goes. Usually `{ name, attrs: { href: 'mailto:{{email}}' }, values: { email } }`, where
 * the template decides the shape, but designs written through the API can hold a plain string.
 */
function linkUrl(link: unknown): string {
    if (typeof link === 'string') {
        return link
    }
    const { name, attrs, values } = (link ?? {}) as {
        name?: string
        attrs?: Record<string, string>
        values?: Record<string, string>
    }
    if (!values) {
        return ''
    }
    const fallback = name === 'email' ? 'mailto:{{href}}' : name === 'phone' ? 'tel:{{href}}' : '{{href}}'
    return (attrs?.href ?? fallback).replace(/\{\{\s*(\w+)\s*\}\}/g, (_, key) => values[key] ?? '')
}

const TEXT_FORMAT = { bold: 1, italic: 2, strike: 4, underline: 8, code: 16, subscript: 32, superscript: 64 }

function escapeHtml(text: string): string {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function richNodeToHtml(node: Record<string, any>): string {
    const children = (node.children ?? []).map(richNodeToHtml).join('')
    switch (node.type) {
        case 'linebreak':
            return '<br />'
        case 'text':
        case 'extended-text':
        case 'merge_tag': {
            let html = escapeHtml(String(node.text ?? '')).replace(/&quot;/g, '"')
            const format = Number(node.format) || 0
            if (format & TEXT_FORMAT.code) {
                html = `<code>${html}</code>`
            }
            if (format & TEXT_FORMAT.subscript) {
                html = `<sub>${html}</sub>`
            }
            if (format & TEXT_FORMAT.superscript) {
                html = `<sup>${html}</sup>`
            }
            if (format & TEXT_FORMAT.underline) {
                html = `<u>${html}</u>`
            }
            if (format & TEXT_FORMAT.strike) {
                html = `<s>${html}</s>`
            }
            if (format & TEXT_FORMAT.italic) {
                html = `<em>${html}</em>`
            }
            if (format & TEXT_FORMAT.bold) {
                html = `<strong>${html}</strong>`
            }
            return node.style ? `<span style="${escapeHtml(String(node.style))}">${html}</span>` : html
        }
        case 'link':
        case 'extended-link':
            return `<a href="${escapeHtml(node.values ? linkUrl(node.values) || String(node.url ?? '') : String(node.url ?? ''))}"${node.style ? ` style="${escapeHtml(String(node.style))}"` : ''}>${children}</a>`
        case 'list':
        case 'extended-list': {
            const tag = node.listType === 'number' ? 'ol' : 'ul'
            return `<${tag}>${children}</${tag}>`
        }
        case 'listitem':
        case 'extended-listitem':
            return `<li>${children}</li>`
        case 'root':
            return children
        default: {
            const alignment = node.format ? ` style="text-align:${escapeHtml(String(node.format))}"` : ''
            return `<p${alignment}>${children || '<br />'}</p>`
        }
    }
}

/** Newer old-editor blocks can keep their text only in `textJson`, and the old editor renders `text` when it has both. */
function richTextOf(values: Record<string, any>): string {
    const text = String(values.text ?? '')
    if (text.trim() || !values.textJson) {
        return text
    }
    try {
        const parsed = typeof values.textJson === 'string' ? JSON.parse(values.textJson) : values.textJson
        return richNodeToHtml(parsed.root ?? parsed)
    } catch {
        return text
    }
}

/** A heading or button label can wrap its text in one styled paragraph, whose styling then belongs to the block. */
function labelStyleOf(html: string, fontSize: number): EmailBlockStyle {
    const body = new DOMParser().parseFromString(html, 'text/html').body
    const only = body.children.length === 1 && !body.children[0].previousSibling ? body.children[0] : null
    if (!only || !['P', 'DIV', 'SPAN'].includes(only.tagName) || only.nextSibling) {
        return {}
    }
    const css = cssOf(only)
    return {
        color: css['color'] || undefined,
        fontWeight: css['font-weight'] ? parseFontWeight(css['font-weight']) : undefined,
        lineHeight: lineHeightPercent(css['line-height'], fontSize),
        textAlign: align(css['text-align']),
    }
}

function inlineContent(html: string): JSONContent[] {
    const body = new DOMParser().parseFromString(html, 'text/html').body
    Array.from(body.children).forEach((child) => {
        if (child.tagName === 'P' || child.tagName === 'DIV') {
            ;(child as HTMLElement).style.removeProperty('font-weight')
        }
    })
    const blocks = chipsInText(generateJSON(body.innerHTML, buildEmailExtensions('')).content) ?? []
    return blocks.flatMap((block, index): JSONContent[] => [
        ...(index > 0 ? [{ type: 'hardBreak' }] : []),
        ...(block.content ?? []),
    ])
}

const IGNORED_CSS =
    /^(-webkit-|-moz-|-ms-|mso-|font-variant|font-stretch|font-kerning|font-feature|font-optical|font-synthesis|orphans|widows|text-indent|word-spacing|white-space|text-decoration-(color|style|thickness)|caret|box-sizing|text-size-adjust|word-wrap|overflow-wrap|word-break|text-rendering|outline|text-align-last)/
const NO_EFFECT = /^(0|0px|none|transparent|normal|auto|inherit|baseline|inline|initial|unset)(\s+(0|0px|none))*$/i
const INLINE_CSS = new Set([
    'color',
    'font-size',
    'font-family',
    'font-weight',
    'font-style',
    'text-decoration',
    'text-decoration-line',
    'letter-spacing',
    'line-height',
    'background-color',
    'text-transform',
])
const BLOCK_CSS = new Set([
    'color',
    'font-size',
    'font-family',
    'font-weight',
    'font-style',
    'line-height',
    'letter-spacing',
    'text-align',
    'text-transform',
    'margin',
    'margin-top',
    'margin-right',
    'margin-bottom',
    'margin-left',
    'margin-block',
    'margin-block-start',
    'margin-block-end',
    'padding',
    'padding-top',
    'padding-right',
    'padding-bottom',
    'padding-left',
    'background-color',
])
const INLINE_TAGS = new Set(['SPAN', 'A', 'STRONG', 'B', 'EM', 'I', 'U', 'S', 'STRIKE', 'DEL', 'BR', 'FONT', 'CODE'])
const HEADING_SIZE: Record<string, number> = { H1: 2, H2: 1.5, H3: 1.17, H4: 1, H5: 0.83, H6: 0.67 }
const HEADING_MARGIN: Record<string, number> = { H1: 0.67, H2: 0.83, H3: 1, H4: 1.33, H5: 1.67, H6: 2.33 }

function cssOf(element: Element): Record<string, string> {
    const declarations: Record<string, string> = {}
    for (const declaration of (element.getAttribute('style') ?? '').split(';')) {
        const colon = declaration.indexOf(':')
        if (colon > 0) {
            declarations[declaration.slice(0, colon).trim().toLowerCase()] = declaration
                .slice(colon + 1)
                .replace(/!important/i, '')
                .trim()
        }
    }
    return declarations
}

function canKeepCss(css: Record<string, string>, supported: Set<string>): boolean {
    return Object.entries(css).every(([name, value]) => {
        if (IGNORED_CSS.test(name) || NO_EFFECT.test(value)) {
            return true
        }
        if (name === 'font-size' && !/^-?[\d.]+px$/.test(value)) {
            return false
        }
        if (name === 'text-align' && !['left', 'center', 'right', 'start'].includes(value)) {
            return false
        }
        return supported.has(name)
    })
}

/** A link opted out of click tracking. The editor's links can't carry that, so the text has to stay as written. */
function isUntrackedLink(element: Element): boolean {
    return (
        element.tagName === 'A' &&
        (element.getAttribute('clicktracking')?.toLowerCase() === 'off' ||
            element.hasAttribute('data-ph-no-track') ||
            element.hasAttribute('ses:no-track'))
    )
}

function canKeepInline(element: Element, insideBold = false): boolean {
    return Array.from(element.children).every((child) => {
        if (!INLINE_TAGS.has(child.tagName) || isUntrackedLink(child)) {
            return false
        }
        const css = cssOf(child)
        const weight = css['font-weight']
        const isBold = insideBold || ['STRONG', 'B'].includes(child.tagName)
        if (insideBold && weight && /^(normal|[1-4]00)$/.test(weight)) {
            return false
        }
        return canKeepCss(css, INLINE_CSS) && canKeepInline(child, isBold)
    })
}

function canKeepTree(block: Element): boolean {
    if (!canKeepCss(cssOf(block), BLOCK_CSS)) {
        return false
    }
    if (block.tagName === 'UL' || block.tagName === 'OL') {
        return Array.from(block.children).every(
            (item) =>
                item.tagName === 'LI' &&
                Object.keys(cssOf(item)).every((name) => IGNORED_CSS.test(name) || name.startsWith('margin')) &&
                Array.from(item.children).every((child) =>
                    isUntrackedLink(child)
                        ? false
                        : INLINE_TAGS.has(child.tagName)
                          ? canKeepCss(cssOf(child), INLINE_CSS) && canKeepInline(child)
                          : child.tagName === 'P' && canKeepCss(cssOf(child), BLOCK_CSS) && canKeepInline(child)
                )
        )
    }
    return canKeepInline(block)
}

function cssSides(css: Record<string, string>, name: string, fontSize: number): EmailSides {
    const length = (value: string | undefined, fallback: number): number => {
        if (!value) {
            return fallback
        }
        const number = parseFloat(value)
        return !Number.isFinite(number) ? fallback : value.endsWith('em') ? number * fontSize : number
    }
    const parts = (css[name] ?? '').split(/\s+/).filter(Boolean)
    const [t, r = t, b = t, l = r] = parts
    const block = (css[`${name}-block`] ?? '').split(/\s+/).filter(Boolean)
    const blockStart = css[`${name}-block-start`] ?? block[0]
    const blockEnd = css[`${name}-block-end`] ?? block[1] ?? block[0]
    return {
        top: length(css[`${name}-top`] ?? blockStart ?? t, -1),
        right: length(css[`${name}-right`] ?? r, -1),
        bottom: length(css[`${name}-bottom`] ?? blockEnd ?? b, -1),
        left: length(css[`${name}-left`] ?? l, -1),
    }
}

function lineHeightPercent(value: string | undefined, fontSize: number): number | undefined {
    if (!value || !/\d/.test(value)) {
        return undefined
    }
    const number = parseFloat(value)
    return value.endsWith('%') ? number : value.endsWith('px') ? (number / fontSize) * 100 : number * 100
}

/**
 * Turns the old editor's rich text into blocks, keeping each paragraph's own styling and the space between them.
 * If it uses anything the blocks can't hold, it stays as the markup it already is.
 */
function richTextBlocks(html: string, style: EmailBlockStyle): JSONContent[] {
    const body = new DOMParser().parseFromString(html, 'text/html').body
    let wrapper: HTMLElement | null = null
    for (const child of Array.from(body.childNodes)) {
        const isInline = child.nodeType === 3 || (child.nodeType === 1 && INLINE_TAGS.has((child as Element).tagName))
        if (isInline) {
            if (child.nodeType === 3 && !child.textContent?.trim() && !wrapper) {
                child.remove()
                continue
            }
            wrapper = wrapper ?? body.insertBefore(body.ownerDocument.createElement('p'), child)
            wrapper.appendChild(child)
        } else {
            wrapper = null
        }
    }
    // A paragraph holding only spaces (not a line break or &nbsp;) has no height in the old editor.
    const hasHeight = (element: Element): boolean =>
        !['P', 'DIV'].includes(element.tagName) ||
        /[^ \t\n\r\f]/.test(element.textContent ?? '') ||
        !!element.querySelector('br, img') ||
        !!(element as HTMLElement).getAttribute('style')?.match(/padding|height|border|margin[^;]*[1-9]/)
    const all = Array.from(body.children)
    const elements = all.some(hasHeight) ? all.filter(hasHeight) : all
    const supported = elements.every(
        (element) =>
            (element.tagName === 'P' ||
                element.tagName === 'DIV' ||
                element.tagName === 'UL' ||
                element.tagName === 'OL' ||
                element.tagName in HEADING_SIZE) &&
            canKeepTree(element)
    )
    if (!supported) {
        return [textAsHtmlBlock(html, style)]
    }
    const baseSize = style.fontSize ?? 14
    const padding = style.padding ?? { top: 0, right: 0, bottom: 0, left: 0 }
    const parsed = elements.map((element) => {
        const css = cssOf(element)
        const headingSize = HEADING_SIZE[element.tagName]
        const fontSize = css['font-size']
            ? parseFloat(css['font-size'])
            : headingSize
              ? headingSize * baseSize
              : baseSize
        const isList = element.tagName === 'UL' || element.tagName === 'OL'
        const defaultMargin = headingSize ? HEADING_MARGIN[element.tagName] * fontSize : isList ? fontSize : 0
        const margin = cssSides(css, 'margin', fontSize)
        const inner = cssSides(css, 'padding', fontSize)
        const number = <T>(value: number, fallback: T): number | T => (value >= 0 ? value : fallback)
        return {
            element,
            css,
            fontSize,
            headingSize,
            isList,
            marginTop: number(margin.top, defaultMargin),
            marginBottom: number(margin.bottom, defaultMargin),
            sides: {
                right: number(margin.right, 0) + number(inner.right, 0),
                left: number(margin.left, 0) + number(inner.left, isList ? 0 : 0),
                top: number(inner.top, 0),
                bottom: number(inner.bottom, 0),
            },
            listIndent: isList ? number(inner.left, 40) : undefined,
        }
    })
    const extensions = buildEmailExtensions('')
    return parsed.flatMap((block, index) => {
        const { element, css } = block
        const previous = parsed[index - 1]
        const next = parsed[index + 1]
        const top = previous ? Math.max(previous.marginBottom, block.marginTop) : padding.top + block.marginTop
        const bottom = next ? 0 : padding.bottom + block.marginBottom
        const fontWeight = css['font-weight'] ? parseFontWeight(css['font-weight']) : undefined
        const blockStyle = compact({
            ...style,
            color: css['color'] || style.color,
            fontSize: block.fontSize,
            fontFamily: css['font-family'] || style.fontFamily,
            fontWeight: fontWeight ?? (block.headingSize ? 700 : style.fontWeight),
            // The old editor's `* { line-height: inherit }` hands down a fixed height, worked out from the block's size.
            lineHeight:
                lineHeightPercent(css['line-height'], block.fontSize) ??
                (style.lineHeight !== undefined ? (style.lineHeight * baseSize) / block.fontSize : undefined),
            letterSpacing: css['letter-spacing'] ? parseFloat(css['letter-spacing']) : style.letterSpacing,
            textAlign: align(css['text-align']) ?? style.textAlign,
            uppercase: css['text-transform'] === 'uppercase' ? true : style.uppercase,
            backgroundColor: css['background-color'] || style.backgroundColor,
            listIndent: block.listIndent,
            listItemGap: block.isList ? 0 : undefined,
            padding: {
                top: top + block.sides.top,
                right: padding.right + block.sides.right,
                bottom: bottom + block.sides.bottom,
                left: padding.left + block.sides.left,
            },
        })
        // The email has only three heading sizes, so a smaller heading is a bold paragraph with its own size.
        ;(element as HTMLElement).style?.removeProperty('font-weight')
        const source =
            element.tagName === 'DIV' || block.headingSize === undefined
                ? element.tagName === 'DIV'
                    ? `<p>${element.innerHTML}</p>`
                    : element.outerHTML
                : ['H1', 'H2', 'H3'].includes(element.tagName)
                  ? element.outerHTML
                  : `<p>${element.innerHTML}</p>`
        const nodes = chipsInText(generateJSON(source, extensions).content) ?? []
        return nodes.map((node) => ({ ...node, attrs: { ...node.attrs, emailStyle: blockStyle } }))
    })
}

function parseFontWeight(value: string): number | undefined {
    if (value === 'bold' || value === 'bolder') {
        return 700
    }
    if (value === 'normal') {
        return 400
    }
    return parsePx(value)
}

const BORDER_SIDES = ['Top', 'Right', 'Bottom', 'Left']

/** A border on every side, or null with none. Anything else can't be drawn the same way, so it's reported. */
function uniformBorder(
    border: Record<string, any> | undefined,
    unsupported: Set<string>,
    what: string
): Pick<EmailBlockStyle, 'borderWidth' | 'borderColor'> | null {
    const widths = BORDER_SIDES.map((side) =>
        border?.[`border${side}Style`] === 'none' ? 0 : (parsePx(border?.[`border${side}Width`]) ?? 0)
    )
    if (widths.every((width) => width === 0)) {
        return null
    }
    const colors = new Set(BORDER_SIDES.map((side) => border?.[`border${side}Color`]))
    const styles = new Set(BORDER_SIDES.map((side) => border?.[`border${side}Style`] ?? 'solid'))
    if (new Set(widths).size > 1 || colors.size > 1 || styles.size > 1 || !styles.has('solid')) {
        unsupported.add(what)
        return null
    }
    return { borderWidth: widths[0], borderColor: [...colors][0] }
}

function fontStyleFrom(values: Record<string, any>): Pick<EmailBlockStyle, 'fontFamily' | 'fontUrl'> {
    // "inherit" picks up the email's font in the old layout, which is what no font means here.
    const family = values.fontFamily?.value === 'inherit' ? undefined : values.fontFamily?.value
    return { fontFamily: family || undefined, fontUrl: values.fontFamily?.url || undefined }
}

interface TextDefaults {
    fontSize: number
    lineHeight: number
}

/** Designs written through the API can hold a bare multiplier, like 1.6, where the old editor's own use a percentage. */
function lineHeightOf(value: unknown): number | undefined {
    const number = parsePx(value)
    return number !== undefined && number > 0 && number < 8 ? number * 100 : number
}

function textStyleFrom(values: Record<string, any>, defaults: TextDefaults): EmailBlockStyle {
    const linkStyle = values.linkStyle
    return {
        ...fontStyleFrom(values),
        fontWeight: parsePx(values.fontWeight),
        color: values.color || undefined,
        fontSize: parsePx(values.fontSize) ?? defaults.fontSize,
        lineHeight: lineHeightOf(values.lineHeight) ?? defaults.lineHeight,
        letterSpacing: parsePx(values.letterSpacing) || undefined,
        textAlign: align(values.textAlign),
        padding: containerPadding(values),
        backgroundColor: values.backgroundColor || undefined,
        linkColor: linkStyle?.linkColor && !linkStyle.inherit ? linkStyle.linkColor : undefined,
        linkUnderline: linkStyle?.linkUnderline === false && !linkStyle.inherit ? false : undefined,
    }
}

/** Text the editor can't hold faithfully stays as the markup it already is, so nothing about it changes. */
function textAsHtmlBlock(html: string, style: EmailBlockStyle): JSONContent {
    const textCss = [
        style.fontFamily ? `font-family:${style.fontFamily.replace(/"/g, "'")}` : '',
        style.fontSize ? `font-size:${style.fontSize}px` : '',
        style.fontWeight ? `font-weight:${style.fontWeight}` : '',
        style.lineHeight ? `line-height:${style.lineHeight}%` : '',
        style.letterSpacing ? `letter-spacing:${style.letterSpacing}px` : '',
        style.color ? `color:${style.color}` : '',
        style.textAlign ? `text-align:${style.textAlign}` : '',
    ]
        .filter(Boolean)
        .join(';')
    return {
        type: 'emailHtml',
        attrs: {
            html: `<div style="${textCss}">${html}</div>`,
            emailStyle: compact({ padding: style.padding, fontUrl: style.fontUrl, inheritText: true }),
        },
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
            const url = String(icon.url ?? '')
            const href = (name === 'Email' && !/^mailto:/i.test(url) ? `mailto:${url}` : url).replace(/"/g, '&quot;')
            return `<td style="padding:0 ${spacing / 2}px"><a href="${href}" target="_blank"><img src="https://cdn.tools.unlayer.com/social/icons/${iconType}/${file}.png" alt="${name.replace(/"/g, '&quot;')}" width="${size}" height="${size}" style="display:block;border:0" /></a></td>`
        })
        .join('')
    return `<table role="presentation" align="${align(values.align) ?? 'center'}" cellpadding="0" cellspacing="0" border="0"><tr>${cells}</tr></table>`
}

function hexColor(value: unknown, fallback: string): string {
    return /^#[0-9a-f]{3,8}$/i.test(String(value ?? '')) ? String(value) : fallback
}

function menuItemCss(values: Record<string, any>): string {
    const fontFamily = fontStyleFrom(values).fontFamily?.replace(/["<>;]/g, '')
    const fontWeight = parsePx(values.fontWeight)
    const letterSpacing = parsePx(values.letterSpacing)
    return [
        `padding:${String(values.padding ?? '5px 15px').replace(/[^0-9a-z .%-]/gi, '')}`,
        `display:${values.layout === 'vertical' ? 'block' : 'inline-block'}`,
        `font-size:${parsePx(values.fontSize) ?? 14}px`,
        fontFamily && `font-family:${fontFamily}`,
        fontWeight && `font-weight:${fontWeight}`,
        letterSpacing && `letter-spacing:${letterSpacing}px`,
    ]
        .filter(Boolean)
        .join(';')
}

function menuItemHtml(item: { text?: string; link?: any }, values: Record<string, any>, itemCss: string): string {
    const text = escapeHtml(String(item.text ?? ''))
    const href = linkUrl(item.link)
    if (!href) {
        return `<span style="${itemCss};color:${hexColor(values.textColor, '#444444')}">${text}</span>`
    }
    const target = item.link?.values?.target === '_self' ? '_self' : '_blank'
    return `<a href="${escapeHtml(href)}" target="${target}" style="${itemCss};color:${hexColor(values.linkColor, '#0068A5')};text-decoration:none">${text}</a>`
}

function menuHtml(values: Record<string, any>): string {
    const itemCss = menuItemCss(values)
    const items = (values.menu?.items ?? []).map((item: { text?: string }) => menuItemHtml(item, values, itemCss))
    const separator = values.layout === 'vertical' ? '' : String(values.separator ?? '')
    // The old editor hides the separator on phones, with a rule every converted email keeps.
    const between = separator
        ? ` ${menuItemHtml({ text: separator }, values, itemCss).replace('<span ', '<span class="hide-mobile" ')} `
        : ' '
    return `<div style="text-align:${align(values.align) ?? 'center'}">${items.join(between)}</div>`
}

function menuBlocks(values: Record<string, any>): JSONContent[] {
    const padding = containerPadding(values)
    if (values.menu?.items?.length) {
        return [
            {
                type: 'emailHtml',
                attrs: { html: menuHtml(values), emailStyle: compact({ padding, inheritText: true }) },
            },
        ]
    }
    // An empty menu still took up its padding in the old editor.
    const height = (padding?.top ?? 0) + (padding?.bottom ?? 0)
    return height ? [{ type: 'emailSpacer', attrs: { height } }] : []
}

// The markup this editor writes for a spacer, which the old editor keeps as an HTML block.
const EXPORTED_SPACER =
    /^<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr><td height="(\d+)"(?: bgcolor="([^"]+)")? style="[^"]*">&nbsp;<\/td><\/tr><\/table>$/

function exportedSpacer(values: Record<string, any>): JSONContent | null {
    const match = EXPORTED_SPACER.exec(String(values.html ?? '').trim())
    if (!match) {
        return null
    }
    const padding = containerPadding(values)
    const height = Number(match[1]) + (padding?.top ?? 0) + (padding?.bottom ?? 0)
    return { type: 'emailSpacer', attrs: { height, ...(match[2] ? { backgroundColor: match[2] } : {}) } }
}

function isSpacerRow(row: any): boolean {
    const contents = row.columns?.length === 1 ? (row.columns[0].contents ?? []) : []
    return contents.length === 1 && contents[0].type === 'html' && !!exportedSpacer(contents[0].values ?? {})
}

function mostCommon(values: string[]): string {
    const counts = new Map<string, number>()
    for (const value of values) {
        counts.set(value, (counts.get(value) ?? 0) + 1)
    }
    return [...counts.entries()].reduce<[string, number]>(
        (best, entry) => (entry[1] > best[1] ? entry : best),
        ['', 0]
    )[0]
}

function isRightToLeft(values: Record<string, any>): boolean {
    return values.direction === 'rtl' || /\bdir=["']?rtl/i.test(String(values.text ?? ''))
}

function convertContent(
    content: Record<string, any>,
    contentWidth: number,
    rowSidePadding: number,
    unsupported: Set<string>,
    notKept: Set<string>
): JSONContent[] {
    const values = content.values ?? {}
    if (isRightToLeft(values)) {
        unsupported.add('right-to-left text')
    }
    if (values.displayCondition) {
        unsupported.add('blocks shown on a condition')
    }
    if (values.hideDesktop || values.hideMobile) {
        unsupported.add('blocks hidden on some screen sizes')
    }
    switch (content.type) {
        case 'text':
        case 'paragraph':
            return richTextBlocks(richTextOf(values), textStyleFrom(values, { fontSize: 14, lineHeight: 140 }))
        case 'heading': {
            const level = Math.min(3, parseInt(String(values.headingType ?? 'h1').slice(1), 10) || 1)
            const style = textStyleFrom(values, { fontSize: 22, lineHeight: 140 })
            return [
                {
                    type: 'heading',
                    attrs: {
                        level,
                        emailStyle: compact({
                            ...style,
                            fontWeight: style.fontWeight ?? 400,
                            ...compact(labelStyleOf(richTextOf(values), style.fontSize ?? 22)),
                        }),
                    },
                    content: inlineContent(richTextOf(values)),
                },
            ]
        }
        case 'button': {
            const colors = values.buttonColors ?? {}
            const inner = parseSides(values.padding ?? '10px 20px')
            const hover = colors.hoverBackgroundColor
            if (hover && hover !== colors.backgroundColor) {
                notKept.add('button colors on hover')
            }
            const text = richTextOf(values)
            const fontSize = parsePx(values.fontSize) ?? 14
            return [
                {
                    type: 'emailButton',
                    attrs: {
                        href: linkUrl(values.href) || linkUrl(values.action),
                        emailStyle: compact({
                            backgroundColor: colors.backgroundColor || '#0879A1',
                            color: colors.color || '#FFFFFF',
                            ...fontStyleFrom(values),
                            ...uniformBorder(values.border, unsupported, 'buttons with a border on only some sides'),
                            buttonWidth:
                                values.size?.autoWidth === false ? (parsePx(values.size?.width) ?? 100) : undefined,
                            fontSize,
                            fontWeight: parsePx(values.fontWeight) ?? 400,
                            lineHeight: lineHeightOf(values.lineHeight),
                            letterSpacing: parsePx(values.letterSpacing) || undefined,
                            // Without a unit the old editor's value is invalid CSS, so the corners stay square.
                            borderRadius:
                                typeof values.borderRadius === 'number' ? 0 : (parsePx(values.borderRadius) ?? 4),
                            innerPaddingX: inner?.left,
                            innerPaddingY: inner?.top,
                            textAlign: align(values.textAlign),
                            padding: containerPadding(values),
                            ...compact(labelStyleOf(text, fontSize)),
                        }),
                    },
                    content: inlineContent(text),
                },
            ]
        }
        case 'image': {
            const src = values.src ?? {}
            const padding = containerPadding(values)
            const available = contentWidth - (padding?.left ?? 0) - (padding?.right ?? 0)
            const percentBase = available - rowSidePadding
            const percent =
                typeof src.maxWidth === 'string' && src.maxWidth.endsWith('%') ? parseFloat(src.maxWidth) : null
            const width =
                src.autoWidth === false && percent ? Math.round((percentBase * percent) / 100) : parsePx(src.width)
            return [
                {
                    type: 'emailImage',
                    attrs: {
                        src: src.url ?? '',
                        alt: values.altText ?? '',
                        href: linkUrl(values.action),
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
                            padding: containerPadding(values),
                        }),
                    },
                },
            ]
        }
        case 'html': {
            const spacer = exportedSpacer(values)
            if (spacer) {
                return [spacer]
            }
            return [
                {
                    type: 'emailHtml',
                    attrs: {
                        html: String(values.html ?? ''),
                        emailStyle: compact({ padding: containerPadding(values), inheritText: true }),
                    },
                },
            ]
        }
        case 'social':
            return [
                {
                    type: 'emailHtml',
                    attrs: {
                        html: socialIconsHtml(values),
                        emailStyle: compact({ padding: containerPadding(values), inheritText: true }),
                    },
                },
            ]
        case 'menu':
            return menuBlocks(values)
        case 'custom':
            if (content.slug === 'unsubscribe_link') {
                return richTextBlocks(
                    String(values.unsubscribe_link_content ?? ''),
                    textStyleFrom(values, { fontSize: 14, lineHeight: 140 })
                )
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
export function unlayerToEmailDocument(
    design: Record<string, any> | null | undefined,
    storedHtml?: string | null
): EmailDocumentConversion {
    const body = design?.body
    if (!body || !Array.isArray(body.rows)) {
        return { document: null, unsupported: ['a design this editor can’t read'], notKept: [] }
    }
    const unsupported = new Set<string>()
    const notKept = new Set<string>()
    const bodyValues = body.values ?? {}
    const rows: any[] = [...(body.headers ?? []), ...body.rows, ...(body.footers ?? [])]
    const bodyWidth = parsePx(bodyValues.contentWidth) ?? 500
    if (bodyValues.backgroundImage?.url) {
        unsupported.add('background images')
    }

    const rowBackgrounds = new Set(rows.map((row) => row.values?.backgroundColor ?? ''))
    const sharedRowBackground = rowBackgrounds.size === 1 ? [...rowBackgrounds][0] : ''
    // A spacer's row takes the color around it, so it says nothing about the body's color.
    const columnBackgrounds: string[] = rows
        .filter((row) => !isSpacerRow(row))
        .flatMap((row) => (row.columns ?? []).map((column: any) => column.values?.backgroundColor ?? ''))
    // When every column is colored, the most common color is the body's and only the others keep a color of their own.
    const sharedColumnBackground =
        new Set(columnBackgrounds).size === 1 || columnBackgrounds.every(Boolean) ? mostCommon(columnBackgrounds) : ''

    const page: Partial<EmailPageStyle> = {
        oldEditorStyles: true,
        backgroundColor: sharedRowBackground || bodyValues.backgroundColor || '#ffffff',
        bodyBackgroundColor: sharedColumnBackground || bodyValues.backgroundColor || '#ffffff',
        bodyWidth,
        bodyPadding: { top: 0, right: 0, bottom: 0, left: 0 },
        align: align(bodyValues.contentAlign) ?? 'center',
        fontFamily: bodyValues.fontFamily?.value || 'arial,helvetica,sans-serif',
        ...(bodyValues.fontFamily?.url ? { fontUrl: bodyValues.fontFamily.url } : {}),
        ...(bodyValues.preheaderText ? { previewText: bodyValues.preheaderText } : {}),
        textColor: bodyValues.textColor || '#000000',
        linkColor: bodyValues.linkStyle?.linkColor || '#0000ee',
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
        // Row padding only sits around the old editor's fixed-width row, so its sides never change the layout.
        const parsedRowPadding = parseSides(rowValues.padding)
        const rowPadding = parsedRowPadding ? { ...parsedRowPadding, left: 0, right: 0 } : undefined
        const rowHasPadding = rowPadding && (rowPadding.top || rowPadding.right || rowPadding.bottom || rowPadding.left)
        const columnsBackground =
            rowValues.columnsBackgroundColor && rowValues.columnsBackgroundColor !== 'transparent'
                ? rowValues.columnsBackgroundColor
                : ''
        const sectionBackground =
            columnsBackground ||
            (rowValues.backgroundColor && rowValues.backgroundColor !== page.backgroundColor
                ? rowValues.backgroundColor
                : '') ||
            ''
        // The old editor paints the columns color inside the row padding, so that padding shows the color behind the
        // row. One section can't hold both colors, so the padding becomes spacers above and below it.
        const behindRow = rowValues.backgroundColor || bodyValues.backgroundColor || '#ffffff'
        const paddingAsSpacers =
            !!rowHasPadding && !!columnsBackground && columnsBackground.toLowerCase() !== behindRow.toLowerCase()
        const spacer = (height: number): JSONContent[] =>
            height
                ? [
                      {
                          type: 'emailSpacer',
                          attrs: {
                              height,
                              ...(behindRow !== page.bodyBackgroundColor ? { backgroundColor: behindRow } : {}),
                          },
                      },
                  ]
                : []

        const rowWidth = bodyWidth
        const converted = columns.map((column, index) => {
            const columnPadding = parseSides(column.values?.padding)
            const width =
                (rowWidth * (cells[index] ?? 1)) / totalCells -
                (columnPadding ? columnPadding.left + columnPadding.right : 0)
            const blocks = (column.contents ?? []).flatMap((item: any) =>
                convertContent(
                    item,
                    width,
                    (parsedRowPadding?.left ?? 0) + (parsedRowPadding?.right ?? 0),
                    unsupported,
                    notKept
                )
            )
            const background = column.values?.backgroundColor
            const padding = parseSides(column.values?.padding)
            const hasPadding = padding && (padding.top || padding.right || padding.bottom || padding.left)
            return {
                blocks,
                style: compact({
                    backgroundColor: background && background !== page.bodyBackgroundColor ? background : undefined,
                    padding: hasPadding ? padding : undefined,
                    borderRadius: parsePx(column.values?.borderRadius) || undefined,
                    ...uniformBorder(column.values?.border, unsupported, 'columns with a border on only some sides'),
                }),
                ratio: cells[index] ?? 1,
            }
        })

        const plain = converted.length === 1 && !converted[0].style && !sectionBackground && !rowHasPadding
        const onlyColor = converted.length === 1 && Object.keys(converted[0].style ?? {}).join() === 'backgroundColor'
        if (isSpacerRow(row) && onlyColor && !sectionBackground && !rowHasPadding) {
            const spacer = converted[0].blocks[0]
            const backgroundColor = spacer.attrs?.backgroundColor ?? converted[0].style?.backgroundColor
            content.push({ ...spacer, attrs: { ...spacer.attrs, backgroundColor } })
            continue
        }
        if (paddingAsSpacers) {
            content.push(...spacer(rowPadding?.top ?? 0))
        }
        if (plain) {
            content.push(...converted[0].blocks)
            continue
        }
        content.push({
            type: 'emailColumns',
            attrs: {
                emailStyle: compact({
                    backgroundColor: sectionBackground || undefined,
                    padding: rowHasPadding && !paddingAsSpacers ? rowPadding : undefined,
                    columnGap: 0,
                }),
            },
            content: converted.map((column) => ({
                type: 'emailColumn',
                attrs: { ratio: column.ratio, emailStyle: column.style },
                content: column.blocks.length ? column.blocks : [{ type: 'paragraph' }],
            })),
        })
        if (paddingAsSpacers) {
            content.push(...spacer(rowPadding?.bottom ?? 0))
        }
    }

    // Only an email sent exactly as written stays that way. The old editor put anything else in its body.
    const onlyBlock = content.length === 1 ? content[0] : null
    if (onlyBlock?.type === 'emailHtml' && String(onlyBlock.attrs?.html ?? '').trim() !== (storedHtml ?? '').trim()) {
        page.wrapFullHtml = true
    }

    if (unsupported.size) {
        return { document: null, unsupported: [...unsupported], notKept: [...notKept] }
    }
    return {
        document: {
            version: EMAIL_DOCUMENT_VERSION,
            doc: { type: 'doc', attrs: { page }, content: content.length ? content : [{ type: 'paragraph' }] },
        },
        unsupported: [],
        notKept: [...notKept],
    }
}
