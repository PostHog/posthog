import { JSONContent, generateJSON } from '@tiptap/core'

import {
    EmailBlockStyle,
    EmailDocument,
    EMAIL_DOCUMENT_VERSION,
    EmailPageStyle,
    EmailPhoneStyle,
    EmailSides,
    EmailTextAlign,
    EmailVisibility,
    emptyEmailDoc,
    safeBackgroundImage,
} from './emailDocument'
import { buildEmailExtensions } from './emailExtensions'
import { parseLiquidOutput } from './emailVariables'
import { renderEmailHtml } from './renderEmailHtml'

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
    /** What only converts as the old editor's own html, which is sent unchanged but edited as code. */
    keptAsHtml?: string[]
}

function parsePx(value: unknown): number | undefined {
    const number = parseFloat(String(value ?? ''))
    return Number.isFinite(number) ? number : undefined
}

function cssPx(value: string | undefined, fontSize: number): number | undefined {
    const match = /^(-?\d*\.?\d+)(px|em|rem|%|pt)?$/.exec(value?.trim() ?? '')
    if (!match) {
        return value?.trim() === 'normal' ? 0 : undefined
    }
    const number = parseFloat(match[1])
    const pixels =
        match[2] === 'em'
            ? number * fontSize
            : match[2] === 'rem'
              ? number * 16
              : match[2] === '%'
                ? (number * fontSize) / 100
                : match[2] === 'pt'
                  ? (number * 4) / 3
                  : number
    return Math.round(pixels * 100) / 100
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

function listItemGapOf(list: Element, fontSize: number): number {
    const gaps = Array.from(list.children).map((item) => Math.max(0, cssSides(cssOf(item), 'margin', fontSize).bottom))
    return gaps.length ? Number(mostCommon(gaps.map(String))) : 0
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

/**
 * Bold text at its own weight, such as 600, keeps that weight. The editor's text style carries it, and only reads it
 * from a span.
 */
function keepFontWeights(root: Element): void {
    root.querySelectorAll('strong[style], b[style]').forEach((element) => {
        if (!/^[1-9]00$/.test((element as HTMLElement).style.fontWeight)) {
            return
        }
        const span = element.ownerDocument.createElement('span')
        span.setAttribute('style', element.getAttribute('style') ?? '')
        span.append(...Array.from(element.childNodes))
        element.replaceWith(span)
    })
}

function inlineContent(html: string): JSONContent[] {
    const body = new DOMParser().parseFromString(html, 'text/html').body
    Array.from(body.children).forEach((child) => {
        if (child.tagName === 'P' || child.tagName === 'DIV') {
            ;(child as HTMLElement).style.removeProperty('font-weight')
        }
    })
    keepFontWeights(body)
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
function richTextBlocks(html: string, style: EmailBlockStyle, paragraphMargins = false): JSONContent[] {
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
            ? (cssPx(css['font-size'], baseSize) ?? baseSize)
            : headingSize
              ? headingSize * baseSize
              : baseSize
        const isList = element.tagName === 'UL' || element.tagName === 'OL'
        const defaultMargin = headingSize
            ? HEADING_MARGIN[element.tagName] * fontSize
            : isList || (paragraphMargins && element.tagName === 'P')
              ? fontSize
              : 0
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
            // The last item's own spacing merges into the list's bottom margin, so only the larger one shows.
            marginBottom: isList
                ? Math.max(number(margin.bottom, defaultMargin), listItemGapOf(element, fontSize)) -
                  listItemGapOf(element, fontSize)
                : number(margin.bottom, defaultMargin),
            sides: {
                right: number(margin.right, 0) + number(inner.right, 0),
                // A list's own left padding is where its bullets go, so it becomes the list indent instead.
                left: number(margin.left, 0) + (isList ? 0 : number(inner.left, 0)),
                top: number(inner.top, 0),
                bottom: number(inner.bottom, 0),
            },
            listIndent: isList ? number(inner.left, 40) : undefined,
            listItemGap: isList ? listItemGapOf(element, fontSize) : undefined,
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
            letterSpacing: css['letter-spacing']
                ? (cssPx(css['letter-spacing'], block.fontSize) ?? style.letterSpacing)
                : style.letterSpacing,
            textAlign: align(css['text-align']) ?? style.textAlign,
            uppercase: css['text-transform'] === 'uppercase' ? true : style.uppercase,
            backgroundColor: css['background-color'] || style.backgroundColor,
            listIndent: block.listIndent,
            listItemGap: block.listItemGap,
            padding: {
                top: top + block.sides.top,
                right: padding.right + block.sides.right,
                bottom: bottom + block.sides.bottom,
                left: padding.left + block.sides.left,
            },
        })
        // The email has only three heading sizes, so a smaller heading is a bold paragraph with its own size.
        ;(element as HTMLElement).style?.removeProperty('font-weight')
        keepFontWeights(element)
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
const BORDER_REASONS = new Set(['buttons with a border on only some sides', 'columns with a border on only some sides'])

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

/** A button's border. Unlike a column's, its sides can differ in width, as on a button with a thicker bottom edge. */
function buttonBorder(
    border: Record<string, any> | undefined,
    unsupported: Set<string>
): Pick<EmailBlockStyle, 'borderWidth' | 'borderSides' | 'borderColor'> | null {
    const widths = BORDER_SIDES.map((side) =>
        border?.[`border${side}Style`] === 'none' ? 0 : (parsePx(border?.[`border${side}Width`]) ?? 0)
    )
    if (new Set(widths).size === 1) {
        return uniformBorder(border, unsupported, 'buttons with a border on only some sides')
    }
    const drawn = BORDER_SIDES.filter((_, index) => widths[index] > 0)
    const colors = new Set(drawn.map((side) => border?.[`border${side}Color`]))
    const styles = new Set(drawn.map((side) => border?.[`border${side}Style`] ?? 'solid'))
    if (colors.size > 1 || styles.size > 1 || !styles.has('solid')) {
        unsupported.add('buttons with a border on only some sides')
        return null
    }
    const [top, right, bottom, left] = widths
    return { borderSides: { top, right, bottom, left }, borderColor: [...colors][0] }
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
function lineHeightOf(value: unknown, fontSize: number): number | undefined {
    const number = parsePx(value)
    if (typeof value === 'string' && value.trim().endsWith('px') && number !== undefined) {
        return Math.round((number / fontSize) * 10000) / 100
    }
    return number !== undefined && number > 0 && number < 8 ? number * 100 : number
}

function textStyleFrom(values: Record<string, any>, defaults: TextDefaults): EmailBlockStyle {
    const linkStyle = values.linkStyle
    return {
        ...fontStyleFrom(values),
        fontWeight: parsePx(values.fontWeight),
        color: values.color || undefined,
        fontSize: parsePx(values.fontSize) ?? defaults.fontSize,
        lineHeight:
            lineHeightOf(values.lineHeight, parsePx(values.fontSize) ?? defaults.fontSize) ?? defaults.lineHeight,
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
    const icons: { name?: string; url?: string }[] = values.icons?.icons ?? []
    const cells = icons
        .map((icon, index) => {
            const name = String(icon.name ?? '')
            const file = name.toLowerCase().replace(/[^a-z0-9]/g, '')
            const url = String(icon.url ?? '')
            const href = (name === 'Email' && !/^mailto:/i.test(url) ? `mailto:${url}` : url).replace(/"/g, '&quot;')
            return `<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="display:inline-table;vertical-align:top;margin:0 ${index === icons.length - 1 ? 0 : spacing}px 0 0"><tr><td><a href="${href}" target="_blank"><img src="https://cdn.tools.unlayer.com/social/icons/${iconType}/${file}.png" alt="${name.replace(/"/g, '&quot;')}" width="${size}" height="${size}" style="display:block;border:0" /></a></td></tr></table>`
        })
        // Each icon is its own inline table so they wrap on a narrow screen, as in the old editor. Outlook on Windows
        // ignores inline tables, so it gets one row of cells.
        .join(`<!--[if mso]></td><td style="padding-left:${spacing}px"><![endif]-->`)
    const side = align(values.align) ?? 'center'
    return `<div style="text-align:${side};font-size:0;line-height:0"><!--[if mso]><table role="presentation" align="${side}" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->${cells}<!--[if mso]></td></tr></table><![endif]--></div>`
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

/** Which screen-size settings the old editor wrote into its html. It leaves some out, such as hiding a row on desktops. */
type ExportedScreens = { desktop: boolean; mobile: boolean } | null

function exportedScreens(html: string | null | undefined): ExportedScreens {
    return html?.trim()
        ? {
              desktop: /class="[^"]{0,1000}\bhide-desktop\b/.test(html),
              mobile: /class="[^"]{0,1000}\bhide-mobile\b/.test(html),
          }
        : null
}

/** The old editor's display condition and screen-size settings, as far as its html carries them out. */
function visibilityFrom(values: Record<string, any>, screens: ExportedScreens): EmailVisibility | null {
    const visibility: EmailVisibility = {}
    const condition = values.displayCondition
    if (condition && typeof condition === 'object' && typeof condition.before === 'string') {
        visibility.condition = {
            before: condition.before,
            after: typeof condition.after === 'string' ? condition.after : '',
            ...(condition.label && condition.label !== condition.before ? { label: String(condition.label) } : {}),
        }
    }
    // Newer versions of the old editor keep these in their per-screen settings.
    const hideDesktop = values.hideDesktop === true || values._override?.desktop?.hideDesktop === true
    const hideMobile = values.hideMobile === true || values._override?.mobile?.hideMobile === true
    if (hideDesktop && (screens?.desktop ?? true)) {
        visibility.hideDesktop = true
    }
    if (hideMobile && (screens?.mobile ?? true)) {
        visibility.hideMobile = true
    }
    return Object.keys(visibility).length ? visibility : null
}

function withVisibility(nodes: JSONContent[], visibility: EmailVisibility | null): JSONContent[] {
    return visibility
        ? nodes.map((node) => ({ ...node, attrs: { ...node.attrs, emailVisibility: visibility } }))
        : nodes
}

/** A condition the old editor can't run, such as one with no Liquid in it, would be sent as text. */
function hasUnknownCondition(values: Record<string, any>): boolean {
    return !!values.displayCondition && typeof values.displayCondition.before !== 'string'
}

interface ConvertContext {
    unsupported: Set<string>
    /** Buttons whose hover colors the old editor's export actually has. Most exports leave them out. */
    hoverButtons: Set<string>
    screens: ExportedScreens
    exportedStyles: ExportedStyles
    /** This block's cell in the old editor's html, when it could be matched to the block. */
    exportedCell?: ExportedCell
    /** The page doesn't reset paragraph margins, as some versions of the old editor's html don't. */
    paragraphMargins: boolean
}

interface ExportedCell {
    first: string
    image?: string
    /** Its text is in paragraphs, which keep the browser's margins unless the page resets them. */
    paragraphs: boolean
}

const CONTENT_CELL =
    /<td(?: class="[^"<>]{0,200}")? style="overflow-wrap:\s?break-word;\s?word-break:\s?break-word;\s?padding:[^"]{0,1000}"[^>]{0,2000}>\s{0,1000}(<[a-z0-9]{1,10}\b[^>]{0,2000}>)?/gi

/**
 * A row's side padding sits outside the old editor's fixed-width row, where the page is wider than the email. Inside
 * the email's body it would push the body wider, so a kept row drops it, as a rebuilt row does.
 */
function withoutRowSidePadding(rowHtml: string): string {
    return rowHtml.replace(
        /^(<div class="u-row-container"[^>]*style="[^"]*?)padding:\s*([^;"]+)/,
        (match, start, value) => {
            const sides = parseSides(value)
            return sides && (sides.left || sides.right)
                ? `${start}padding: ${sides.top}px 0px ${sides.bottom}px 0px`
                : match
        }
    )
}

function exportedContentCells(rowHtml: string | undefined, contentCount: number): ExportedCell[] | null {
    const matches = rowHtml ? [...rowHtml.matchAll(CONTENT_CELL)] : []
    if (!rowHtml || matches.length !== contentCount) {
        return null
    }
    return matches.map((match, index) => {
        const cell = rowHtml.slice(match.index, matches[index + 1]?.index ?? rowHtml.length)
        return {
            first: match[1] ?? '',
            image: /<img\b[^>]{0,4000}>/i.exec(withoutOutlookOnly(cell))?.[0],
            paragraphs: /<p\b/i.test(cell),
        }
    })
}

/**
 * Text the old editor's earlier versions saved without a size or line height went out without one, so mail apps
 * showed their own defaults: 16px and a normal line height of about 115%.
 */
function exportedTextDefaults(element: string | undefined, defaults: TextDefaults): TextDefaults {
    if (!element || !/^<div\b/i.test(element)) {
        return defaults
    }
    const style = /\bstyle="([^"]*)"/i.exec(element)?.[1] ?? ''
    return {
        fontSize: /font-size\s*:/i.test(style) ? defaults.fontSize : 16,
        lineHeight: /line-height\s*:/i.test(style) ? defaults.lineHeight : 115,
    }
}

interface ExportedStyles {
    /** Each block's phone settings as its export writes them, by block id and then by the class they style. */
    phone: Map<string, Map<string, string>>
    images: Map<string, ExportedImage>
}

interface ExportedImage {
    width: number
    scale: number
}

function exportedStyles(storedHtml: string | null | undefined): ExportedStyles {
    const html = storedHtml ?? ''
    const phone = new Map<string, Map<string, string>>()
    for (const [, id, className, declarations] of html.matchAll(
        /#(u_[a-z_]{1,40}_\d{1,9}) ?\.(v-[\w-]{1,60}) \{([^{}]{0,1000})\}/g
    )) {
        const rules = phone.get(id) ?? new Map<string, string>()
        rules.set(className, declarations.replace(/!important/g, '').trim())
        phone.set(id, rules)
    }
    const images = new Map<string, ExportedImage>()
    for (const [, id, image] of withoutOutlookOnly(html).matchAll(
        /id="(u_content_image_\d{1,9})"(?:(?!id="u_)[\s\S]){0,20000}?(<img\b[^>]{0,4000}>)/g
    )) {
        const size = exportedImageSize(image)
        if (size) {
            images.set(id, size)
        }
    }
    return { phone, images }
}

/** Markup only Outlook on Windows reads, such as the fixed-size copy of each image the old editor writes for it. */
function withoutOutlookOnly(html: string): string {
    // A walk rather than a regex, so html with many unclosed comments can't take quadratic time.
    const start = '<!--[if mso]>'
    const end = '<![endif]-->'
    const lower = html.toLowerCase()
    let kept = ''
    let from = 0
    for (let open = lower.indexOf(start); open !== -1; open = lower.indexOf(start, from)) {
        const close = lower.indexOf(end, open + start.length)
        if (close === -1) {
            break
        }
        kept += html.slice(from, open)
        from = close + end.length
    }
    return kept + html.slice(from)
}

function exportedImageSize(image: string | undefined): ExportedImage | null {
    const css = /\bstyle="([^"]*)"/.exec(image ?? '')?.[1] ?? ''
    const cssWidth = /(?:^|;)\s*width:\s*([\d.]+)(px|%)/.exec(css)
    const maxWidth = /max-width:\s*([\d.]+)px/.exec(css)
    const width = parseFloat(maxWidth?.[1] ?? /\swidth="([\d.]+)"/.exec(` ${image ?? ''}`)?.[1] ?? '')
    return width > 0 ? { width: Math.round(width), scale: cssWidth?.[2] === '%' ? parseFloat(cssWidth[1]) : 100 } : null
}

function declaration(rules: Map<string, string> | undefined, className: string, property: string): string | undefined {
    const declarations = rules?.get(className)
    return declarations ? new RegExp(`(?:^|;)\\s*${property}:\\s*([^;]+)`).exec(declarations)?.[1]?.trim() : undefined
}

function phoneStyleFrom(rules: Map<string, string> | undefined): EmailPhoneStyle | undefined {
    if (!rules) {
        return undefined
    }
    const innerPadding = parseSides(declaration(rules, 'v-padding', 'padding'))
    const imageMaxWidth = declaration(rules, 'v-src-max-width', 'max-width')
    const lineHeight = declaration(rules, 'v-line-height', 'line-height')
    const style: EmailPhoneStyle = {
        padding: parseSides(
            declaration(rules, 'v-container-padding-padding', 'padding') ??
                declaration(rules, 'v-col-padding', 'padding')
        ),
        fontSize: parsePx(declaration(rules, 'v-font-size', 'font-size')),
        lineHeight: lineHeight?.endsWith('%') ? parseFloat(lineHeight) : undefined,
        textAlign: align(declaration(rules, 'v-text-align', 'text-align')),
        imageScale: parsePx(declaration(rules, 'v-src-width', 'width')),
        width: imageMaxWidth?.endsWith('px') ? parsePx(imageMaxWidth) : undefined,
        buttonWidth: parsePx(declaration(rules, 'v-size-width', 'width')),
        innerPaddingX: innerPadding?.left,
        innerPaddingY: innerPadding?.top,
        borderRadius: parsePx(declaration(rules, 'v-col-border-radius', 'border-radius')),
        backgroundColor: declaration(rules, 'v-col-background-color', 'background-color'),
    }
    const kept = Object.fromEntries(
        Object.entries(style).filter(([, value]) => value !== undefined && !Number.isNaN(value))
    )
    return Object.keys(kept).length ? kept : undefined
}

function exportedHoverButtons(storedHtml: string | null | undefined): Set<string> {
    return new Set(
        [...(storedHtml ?? '').matchAll(/#(u_content_button_\d{1,9})[^{}]{0,1000}:hover/g)].map((match) => match[1])
    )
}

function convertContent(
    content: Record<string, any>,
    contentWidth: number,
    rowSidePadding: number,
    context: ConvertContext
): JSONContent[] {
    const values = content.values ?? {}
    if (hasUnknownCondition(values)) {
        context.unsupported.add('blocks shown on a condition')
    }
    return withVisibility(
        convertContentBlocks(content, contentWidth, rowSidePadding, context),
        visibilityFrom(values, context.screens)
    )
}

function convertContentBlocks(
    content: Record<string, any>,
    contentWidth: number,
    rowSidePadding: number,
    context: ConvertContext
): JSONContent[] {
    const blocks = convertContentBlocksWithoutPhone(content, contentWidth, rowSidePadding, context)
    const exportedPhone = phoneStyleFrom(context.exportedStyles.phone.get(String(content.values?._meta?.htmlID ?? '')))
    // A line height in pixels stays the same when a phone shrinks the text, so it becomes a larger share of the size.
    const fixedLineHeight =
        typeof content.values?.lineHeight === 'string' && content.values.lineHeight.trim().endsWith('px')
            ? parsePx(content.values.lineHeight)
            : undefined
    const phone =
        exportedPhone?.fontSize && !exportedPhone.lineHeight && fixedLineHeight
            ? { ...exportedPhone, lineHeight: Math.round((fixedLineHeight / exportedPhone.fontSize) * 10000) / 100 }
            : exportedPhone
    return phone
        ? blocks.map((block) => ({
              ...block,
              attrs: { ...block.attrs, emailStyle: { ...block.attrs?.emailStyle, phone } },
          }))
        : blocks
}

function convertContentBlocksWithoutPhone(
    content: Record<string, any>,
    contentWidth: number,
    rowSidePadding: number,
    { unsupported, hoverButtons, exportedStyles: styles, exportedCell, paragraphMargins }: ConvertContext
): JSONContent[] {
    const values = content.values ?? {}
    if (
        (content.type === 'text' || content.type === 'paragraph' || content.type === 'heading') &&
        isRightToLeft(values)
    ) {
        // Right-to-left text keeps its own markup, with the direction on it, and is edited as code.
        const style = textStyleFrom(values, { fontSize: content.type === 'heading' ? 22 : 14, lineHeight: 140 })
        const html = richTextOf(values)
        const level = Math.min(3, parseInt(String(values.headingType ?? 'h1').slice(1), 10) || 1)
        return [
            textAsHtmlBlock(
                `<div dir="rtl">${content.type === 'heading' ? `<h${level} style="margin:0;font-size:inherit">${html}</h${level}>` : html}</div>`,
                style
            ),
        ]
    }
    switch (content.type) {
        case 'text':
        case 'paragraph':
            return richTextBlocks(
                richTextOf(values),
                textStyleFrom(values, exportedTextDefaults(exportedCell?.first, { fontSize: 14, lineHeight: 140 })),
                paragraphMargins && !!exportedCell?.paragraphs
            )
        case 'heading': {
            const level = Math.min(3, parseInt(String(values.headingType ?? 'h1').slice(1), 10) || 1)
            const style = textStyleFrom(values, { fontSize: 22, lineHeight: 140 })
            const headingHtml = richTextOf(values)
            const headingLinks = new DOMParser().parseFromString(headingHtml, 'text/html').body.querySelectorAll('a')
            if (/<h[1-6]\b/i.test(headingHtml)) {
                // A heading inside the heading ends it in every browser, so the inner one shows at its default size.
                // The markup stays as it is, with the heading's styles on its own element.
                const headingCss = [
                    'margin:0',
                    style.fontFamily ? `font-family:${style.fontFamily.replace(/"/g, "'")}` : '',
                    `font-size:${style.fontSize ?? 22}px`,
                    `font-weight:${style.fontWeight ?? 400}`,
                    style.lineHeight ? `line-height:${style.lineHeight}%` : '',
                    style.letterSpacing ? `letter-spacing:${style.letterSpacing}px` : '',
                    style.color ? `color:${style.color}` : '',
                    style.textAlign ? `text-align:${style.textAlign}` : '',
                ]
                    .filter(Boolean)
                    .join(';')
                return [
                    {
                        type: 'emailHtml',
                        attrs: {
                            html: `<h${level} style="${headingCss}">${headingHtml}</h${level}>`,
                            emailStyle: compact({ padding: style.padding, inheritText: true }),
                        },
                    },
                ]
            }
            if (Array.from(headingLinks).some(isUntrackedLink)) {
                return [
                    textAsHtmlBlock(`<h${level}>${headingHtml}</h${level}>`, {
                        ...style,
                        fontWeight: style.fontWeight ?? 400,
                    }),
                ]
            }
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
            const text = richTextOf(values)
            const fontSize = parsePx(values.fontSize) ?? 14
            const hover = hoverButtons.has(String(values._meta?.htmlID ?? content.id ?? ''))
            return [
                {
                    type: 'emailButton',
                    attrs: {
                        href: linkUrl(values.href) || linkUrl(values.action),
                        emailStyle: compact({
                            backgroundColor: colors.backgroundColor || '#0879A1',
                            color: colors.color || '#FFFFFF',
                            hoverBackgroundColor:
                                hover && colors.hoverBackgroundColor !== colors.backgroundColor
                                    ? colors.hoverBackgroundColor || undefined
                                    : undefined,
                            hoverColor:
                                hover && colors.hoverColor !== colors.color
                                    ? colors.hoverColor || undefined
                                    : undefined,
                            ...fontStyleFrom(values),
                            ...buttonBorder(values.border, unsupported),
                            buttonWidth:
                                values.size?.autoWidth === false ? (parsePx(values.size?.width) ?? 100) : undefined,
                            fontSize,
                            fontWeight: parsePx(values.fontWeight) ?? 400,
                            lineHeight: lineHeightOf(values.lineHeight, fontSize),
                            letterSpacing: parsePx(values.letterSpacing) || undefined,
                            // Without a unit the old editor's value is invalid CSS, so the corners stay square.
                            borderRadius:
                                typeof values.borderRadius === 'number' ? 0 : (parsePx(values.borderRadius) ?? 4),
                            innerPaddingX: inner?.left,
                            innerPaddingY: inner?.top,
                            // The old editor centers a button unless told otherwise.
                            textAlign: align(values.textAlign) ?? 'center',
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
            const exportedImage =
                styles.images.get(String(values._meta?.htmlID ?? '')) ?? exportedImageSize(exportedCell?.image)
            const width = exportedImage
                ? exportedImage.width
                : src.autoWidth === false && percent
                  ? Math.round((percentBase * percent) / 100)
                  : parsePx(src.width)
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
                            imageScale:
                                exportedImage?.scale ?? (src.autoWidth === false && percent ? percent : undefined),
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
                // The block exports its content bare, so it takes the email app's size and line height.
                return richTextBlocks(
                    String(values.unsubscribe_link_content ?? ''),
                    textStyleFrom(values, { fontSize: 16, lineHeight: 115 }),
                    paragraphMargins && !!exportedCell?.paragraphs
                )
            }
            unsupported.add(`the custom block ${String(content.slug ?? '')}`.trim())
            return []
        default:
            unsupported.add(UNSUPPORTED_CONTENT[content.type] ?? `${String(content.type)} blocks`)
            return []
    }
}

/** The old editor's export of each row, in order, with the page styles its markup depends on. */
function exportedRows(storedHtml: string | null | undefined): { rows: string[]; css: string } | null {
    if (!storedHtml || !storedHtml.includes('u-row-container')) {
        return null
    }
    const exported = new DOMParser().parseFromString(storedHtml, 'text/html')
    const rows = Array.from(exported.querySelectorAll('.u-row-container'))
        // A row inside another row's markup would be counted twice.
        .filter((row) => !row.parentElement?.closest('.u-row-container'))
        .map((row) => row.outerHTML)
    const css = Array.from(exported.querySelectorAll('style'))
        .map((style) => style.textContent ?? '')
        .join('\n')
        .trim()
    return { rows, css }
}

/** The text with its Liquid tags taken out and handed to `onTag`. A walk, so a flood of braces stays linear. */
function withoutLiquidTags(text: string, onTag: (tag: string) => void): string {
    let kept = ''
    let from = 0
    let open = text.indexOf('{')
    let braceClose = -2
    let percentClose = -2
    while (open !== -1) {
        if (text[open + 1] !== '{' && text[open + 1] !== '%') {
            open = text.indexOf('{', open + 1)
            continue
        }
        // Each search only moves forward, so a missing kind of close isn't searched for again.
        if (braceClose !== -1 && braceClose < open + 2) {
            braceClose = text.indexOf('}}', open + 2)
        }
        if (percentClose !== -1 && percentClose < open + 2) {
            percentClose = text.indexOf('%}', open + 2)
        }
        const closes = [braceClose, percentClose].filter((index) => index !== -1)
        if (!closes.length) {
            break
        }
        const end = Math.min(...closes) + 2
        kept += text.slice(from, open)
        onTag(text.slice(open, end))
        from = end
        open = text.indexOf('{', end)
    }
    return kept + text.slice(from)
}

/**
 * What a reader gets from an email: its words, links and Liquid. Spacing, the quotes around a Liquid fallback and an
 * empty fallback don't change what is sent, so they are left out.
 */
function sentContent(html: string): string {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    doc.querySelectorAll('style, script, head, title').forEach((element) => element.remove())
    const links = Array.from(doc.querySelectorAll('a[href]'))
        .map((link) => (link.getAttribute('href') ?? '').trim())
        .filter(Boolean)
        .sort()
    const space = /[\s\u00a0\u200b-\u200f\u034f\u2060\ufeff\u00ad]+/g
    // Compared as a set, because the parser moves a tag that sits between table rows to before the table.
    const tags: string[] = []
    const words = withoutLiquidTags((doc.body?.textContent ?? '') + links.join(' '), (tag) =>
        tags.push(
            tag
                .replace(/"/g, "'")
                .replace(/\|\s*default:\s*''/g, '')
                .replace(space, '')
        )
    )
    return words.replace(space, '') + tags.sort().join('')
}

function hasOldRowMarkup(node: JSONContent): boolean {
    return node.type === 'emailHtml'
        ? /class="[^"]*\bu-(row|col)\b/.test(String(node.attrs?.html ?? ''))
        : (node.content ?? []).some(hasOldRowMarkup)
}

/** Set by `buildHtmlWrapDesign` in the email templater. */
const HTML_WRAP_BODY_ID = 'html-wrap-body'

/** The whole email as one HTML block, sent exactly as the old editor exported it. */
function wholeEmailAsHtml(storedHtml: string, reasons: string[]): EmailDocumentConversion {
    return {
        document: {
            version: EMAIL_DOCUMENT_VERSION,
            doc: {
                type: 'doc',
                attrs: { page: { oldEditorStyles: true, htmlAsWritten: true } },
                content: [{ type: 'emailHtml', attrs: { html: storedHtml.trim(), emailStyle: null } }],
            },
        },
        unsupported: [],
        notKept: [],
        keptAsHtml: reasons,
    }
}

/**
 * Builds a document from an old-editor design. A row the new editor can't rebuild keeps the old editor's own html for
 * it, so every email converts and sends the same. Nothing is saved until a person accepts the result.
 */
export function unlayerToEmailDocument(
    design: Record<string, any> | null | undefined,
    storedHtml?: string | null
): EmailDocumentConversion {
    const body = design?.body
    if (!body && !storedHtml?.trim()) {
        // Nothing visual to keep, such as an email written only in plain text.
        return {
            document: { version: EMAIL_DOCUMENT_VERSION, doc: emptyEmailDoc() },
            unsupported: [],
            notKept: [],
        }
    }
    // The app's own wrapper around an email saved as raw html, so the html is the whole email. Once the old editor
    // added rows to it, it's an ordinary design.
    const contents = body?.rows?.flatMap((row: any) =>
        (row.columns ?? []).flatMap((column: any) => column.contents ?? [])
    )
    // Html the old editor didn't export, such as an email whose html was sent through the API, is sent as written.
    const exportedByOldEditor = /\bu-row\b|\bu_body\b/.test(storedHtml ?? '')
    if (
        (body?.id === HTML_WRAP_BODY_ID || !exportedByOldEditor) &&
        contents?.length === 1 &&
        contents[0].type === 'html' &&
        storedHtml?.trim()
    ) {
        return wholeEmailAsHtml(storedHtml, [])
    }
    if (!body || !Array.isArray(body.rows)) {
        return storedHtml?.trim()
            ? wholeEmailAsHtml(storedHtml, ['a design this editor can’t read'])
            : { document: null, unsupported: ['a design this editor can’t read'], notKept: [] }
    }
    const unsupported = new Set<string>()
    const keptAsHtml = new Set<string>()
    const notKept = new Set<string>()
    const bodyValues = body.values ?? {}
    const rows: any[] = [...(body.headers ?? []), ...body.rows, ...(body.footers ?? [])]
    const exported = exportedRows(storedHtml)
    const paragraphMargins =
        !!exported && !/(^|[}\s,;])p\s{0,20}\{[^}]{0,200}?margin(?:-top)?\s{0,5}:\s{0,5}0/.test(exported.css)
    // The width the old editor's html actually used wins, as a design can disagree with it. A width in percent can't be
    // a fixed body width, and the old editor's export of it is broken anyway.
    const percentWidth = String(bodyValues.contentWidth ?? '')
        .trim()
        .endsWith('%')
    const exportedWidth = parsePx(
        /\.u-row\s?\{\s{0,20}width:\s?(\d{2,4})px\s?!important/.exec(exported?.css ?? '')?.[1]
    )
    const bodyWidth = percentWidth ? 600 : (exportedWidth ?? parsePx(bodyValues.contentWidth) ?? 500)
    const hoverButtons = exportedHoverButtons(storedHtml)
    const styles = exportedStyles(storedHtml)
    const rowHtml = exported && exported.rows.length === rows.length ? exported.rows : null
    // The last rule wins: the old editor's own drops a row's side padding on phones, and a design's custom CSS can
    // add some back.
    const phoneSideRules = [
        ...(exported?.css ?? '').matchAll(
            /\.u-row-container\s?\{[^{}]{0,400}?padding-left:\s?(\d{1,3})(?:px)?\s?!important/g
        ),
    ]
    const phoneSidePadding = phoneSideRules.length
        ? parseFloat(phoneSideRules[phoneSideRules.length - 1][1])
        : undefined

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
        ...(bodyValues.backgroundImage?.url
            ? {
                  backgroundImage: safeBackgroundImage({
                      url: bodyValues.backgroundImage.url,
                      repeat:
                          bodyValues.backgroundImage.repeat === 'repeat' || bodyValues.backgroundImage.repeat === true,
                      size:
                          bodyValues.backgroundImage.size === 'cover' || bodyValues.backgroundImage.size === 'contain'
                              ? bodyValues.backgroundImage.size
                              : 'auto',
                      position: bodyValues.backgroundImage.position === 'center' ? 'center center' : 'center top',
                      fullWidth: bodyValues.backgroundImage.fullWidth !== false,
                  }),
              }
            : {}),
    }
    if (bodyValues.backgroundImage?.url && !page.backgroundImage) {
        unsupported.add('background images')
    }

    const content: JSONContent[] = []
    for (const [rowIndex, row] of rows.entries()) {
        const rowValues = row.values ?? {}
        const rowUnsupported = new Set<string>()
        const screens = exportedScreens(rowHtml?.[rowIndex] ?? storedHtml)
        const rowVisibility = visibilityFrom(rowValues, screens)
        if (hasUnknownCondition(rowValues)) {
            rowUnsupported.add('rows shown on a condition')
        }
        if (rowValues.backgroundImage?.url) {
            rowUnsupported.add('background images')
        }
        const rowContent: JSONContent[] = []
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
        const exportedCells = exportedContentCells(
            rowHtml?.[rowIndex],
            columns.reduce((total, column) => total + (column.contents?.length ?? 0), 0)
        )
        let contentIndex = 0
        const converted = columns.map((column, index) => {
            const columnPadding = parseSides(column.values?.padding)
            const width =
                (rowWidth * (cells[index] ?? 1)) / totalCells -
                (columnPadding ? columnPadding.left + columnPadding.right : 0)
            const blocks = (column.contents ?? []).flatMap((item: any) =>
                convertContent(item, width, (parsedRowPadding?.left ?? 0) + (parsedRowPadding?.right ?? 0), {
                    unsupported: rowUnsupported,
                    hoverButtons,
                    screens,
                    exportedStyles: styles,
                    exportedCell: exportedCells?.[contentIndex++],
                    paragraphMargins,
                })
            )
            const background = column.values?.backgroundColor
            const padding = parseSides(column.values?.padding)
            const hasPadding = padding && (padding.top || padding.right || padding.bottom || padding.left)
            const columnPhone = phoneStyleFrom(styles.phone.get(String(column.values?._meta?.htmlID ?? '')))
            return {
                blocks,
                style: compact({
                    backgroundColor: background && background !== page.bodyBackgroundColor ? background : undefined,
                    padding: hasPadding ? padding : undefined,
                    borderRadius: parsePx(column.values?.borderRadius) || undefined,
                    ...uniformBorder(column.values?.border, rowUnsupported, 'columns with a border on only some sides'),
                    phone: columnPhone
                        ? (compact({
                              padding: columnPhone.padding,
                              borderRadius: columnPhone.borderRadius,
                              backgroundColor: columnPhone.backgroundColor,
                          }) ?? undefined)
                        : undefined,
                }),
                ratio: cells[index] ?? 1,
            }
        })

        // Older exports don't drop a row's side padding on a phone, where it then narrows the row.
        const rowRules = styles.phone.get(String(rowValues._meta?.htmlID ?? ''))
        const phoneTop = parsePx(declaration(rowRules, 'v-row-padding--vertical', 'padding-top'))
        const phoneBottom = parsePx(declaration(rowRules, 'v-row-padding--vertical', 'padding-bottom'))
        // Older exports have no rule, so a row's own side padding stays on phones.
        const phoneLeft = exported ? (phoneSidePadding ?? parsedRowPadding?.left ?? 0) : 0
        const phoneRight = exported ? (phoneSidePadding ?? parsedRowPadding?.right ?? 0) : 0
        const phoneRowPadding =
            phoneLeft || phoneRight || phoneTop !== undefined || phoneBottom !== undefined
                ? {
                      top: phoneTop ?? parsedRowPadding?.top ?? 0,
                      bottom: phoneBottom ?? parsedRowPadding?.bottom ?? 0,
                      left: phoneLeft,
                      right: phoneRight,
                  }
                : undefined
        const noStack =
            columns.length > 1 &&
            (rowValues.noStackMobile === true || rowValues._override?.mobile?.noStackMobile === true)
        const plain =
            converted.length === 1 &&
            !converted[0].style &&
            !sectionBackground &&
            !rowHasPadding &&
            !rowVisibility &&
            !phoneRowPadding &&
            !noStack
        const onlyColor = converted.length === 1 && Object.keys(converted[0].style ?? {}).join() === 'backgroundColor'
        const rowSpacer =
            isSpacerRow(row) && onlyColor && !sectionBackground && !rowHasPadding ? converted[0].blocks[0] : null
        if (rowSpacer) {
            const backgroundColor = rowSpacer.attrs?.backgroundColor ?? converted[0].style?.backgroundColor
            rowContent.push({
                ...rowSpacer,
                attrs: {
                    ...rowSpacer.attrs,
                    backgroundColor,
                    ...(rowVisibility ? { emailVisibility: rowVisibility } : {}),
                },
            })
        } else {
            if (paddingAsSpacers) {
                rowContent.push(...withVisibility(spacer(rowPadding?.top ?? 0), rowVisibility))
            }
            if (plain) {
                rowContent.push(...converted[0].blocks)
            } else {
                rowContent.push({
                    type: 'emailColumns',
                    attrs: {
                        emailStyle: compact({
                            backgroundColor: sectionBackground || undefined,
                            padding: rowHasPadding && !paddingAsSpacers ? rowPadding : undefined,
                            phone: phoneRowPadding
                                ? {
                                      padding: {
                                          ...phoneRowPadding,
                                          top: paddingAsSpacers ? 0 : phoneRowPadding.top,
                                          bottom: paddingAsSpacers ? 0 : phoneRowPadding.bottom,
                                      },
                                  }
                                : undefined,
                            columnGap: 0,
                            noStack: noStack || undefined,
                        }),
                        ...(rowVisibility ? { emailVisibility: rowVisibility } : {}),
                    },
                    content: converted.map((column) => ({
                        type: 'emailColumn',
                        attrs: { ratio: column.ratio, emailStyle: column.style },
                        content: column.blocks.length ? column.blocks : [{ type: 'paragraph' }],
                    })),
                })
            }
            if (paddingAsSpacers) {
                rowContent.push(...withVisibility(spacer(rowPadding?.bottom ?? 0), rowVisibility))
            }
        }

        if (!rowUnsupported.size) {
            content.push(...rowContent)
        } else if (rowHtml) {
            // The old editor's own html for this row, so it looks and sends the same. Its condition and screen
            // settings sit outside that html, so they carry over as they do for any other block.
            rowUnsupported.forEach((reason) => keptAsHtml.add(reason))
            content.push(
                ...withVisibility(
                    [
                        {
                            type: 'emailHtml',
                            attrs: {
                                html: withoutRowSidePadding(rowHtml[rowIndex]),
                                emailStyle: compact({ inheritText: true }),
                            },
                        },
                    ],
                    rowVisibility
                )
            )
        } else if ([...rowUnsupported].every((reason) => BORDER_REASONS.has(reason))) {
            // With no html to keep, the row is rebuilt with only its uniform borders, and the note says what's lost.
            rowUnsupported.forEach((reason) => notKept.add(reason))
            content.push(...rowContent)
        } else {
            rowUnsupported.forEach((reason) => unsupported.add(reason))
        }
    }

    // Only an email sent exactly as written stays that way. The old editor put anything else in its body.
    const onlyBlock = content.length === 1 ? content[0] : null
    if (onlyBlock?.type === 'emailHtml' && String(onlyBlock.attrs?.html ?? '').trim() !== (storedHtml ?? '').trim()) {
        page.wrapFullHtml = true
    }

    if (unsupported.size) {
        // The rows can't be matched to the exported html, so the email as a whole keeps it.
        return storedHtml?.trim()
            ? wholeEmailAsHtml(storedHtml, [...unsupported])
            : { document: null, unsupported: [...unsupported], notKept: [...notKept] }
    }
    // The old editor's rows lay out with the page styles it exported, such as its column widths. An HTML block can hold
    // a copy of that markup too.
    const usesOldRowMarkup = content.some(hasOldRowMarkup)
    if ((keptAsHtml.size || usesOldRowMarkup) && exported?.css) {
        page.globalCss = exported.css
    }
    const doc: JSONContent = {
        type: 'doc',
        attrs: { page },
        content: content.length ? content : [{ type: 'paragraph' }],
    }
    // A design can fall behind its html, for example after the html was changed through the API. The html is what
    // people receive, so it wins.
    if (storedHtml?.trim() && sentContent(renderEmailHtml(doc)) !== sentContent(storedHtml)) {
        return wholeEmailAsHtml(storedHtml, ['a design that no longer matches the email'])
    }
    // Html the old editor didn't write only shares its words with the design, not its layout.
    if (storedHtml?.trim() && !exportedByOldEditor) {
        return wholeEmailAsHtml(storedHtml, [])
    }
    return {
        document: { version: EMAIL_DOCUMENT_VERSION, doc },
        unsupported: [],
        notKept: [...notKept],
        keptAsHtml: [...keptAsHtml],
    }
}
