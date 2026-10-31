import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

export interface TemplateHtmlFileContent {
    subject: EmailTemplate['subject']
    preheader?: EmailTemplate['preheader'] | null
    html: EmailTemplate['html']
}

interface Span {
    start: number
    end: number
}

interface TitleTag extends Span {
    textStart: number
    textEnd: number
}

interface PreheaderTag extends Span {
    value: string
}

interface HeadScan {
    title?: TitleTag
    preheader?: PreheaderTag
    preheaders: PreheaderTag[]
    headOpenEnd?: number
    htmlOpenEnd?: number
    doctypeEnd?: number
}

interface HeadScanContext {
    html: string
    scan: HeadScan
    titleCanClose: boolean
}

const COMMENT_START = '<!--'
const COMMENT_END = '-->'
const TAG_NAME = /<(?:title|meta)\b/iy
const TAG_ATTRIBUTES = `(?:[^>"']|"[^"]*"|'[^']*')*`
const TITLE_OPEN = new RegExp(`<title\\b${TAG_ATTRIBUTES}>`, 'iy')
const TITLE_CLOSE = /<\/title\s*>/gi
const META_TAG = new RegExp(`<meta\\b${TAG_ATTRIBUTES}>`, 'iy')
const HEAD_OPEN = new RegExp(`<head\\b${TAG_ATTRIBUTES}>`, 'iy')
const HTML_OPEN = new RegExp(`<html\\b${TAG_ATTRIBUTES}>`, 'iy')
const DOCTYPE = /<!doctype\b[^>]*>/iy
const ATTRIBUTE = /([^\s"'=<>/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g
const CHARACTER_REFERENCE = /&(?:#(\d+)|#[xX]([0-9a-fA-F]+)|(amp|lt|gt|quot|apos|nbsp));/g
const NAMED_CHARACTERS: Record<string, string> = {
    amp: '&',
    lt: '<',
    gt: '>',
    quot: '"',
    apos: "'",
    nbsp: String.fromCodePoint(0xa0),
}
const LIQUID = /\{\{[\s\S]*?\}\}|\{%[\s\S]*?%\}/g
const CHARACTER_REFERENCE_START = /&(?=#\d+;|#[xX][0-9a-fA-F]+;|(?:amp|lt|gt|quot|apos|nbsp);)/g
const TITLE_CLOSE_START = /<(?=\/title)/gi

export function templateHtmlFile(email: TemplateHtmlFileContent): string {
    return withPreheader(withSubject(email.html, email.subject), email.preheader ?? '')
}

function withSubject(html: string, subject: string): string {
    const { title, ...head } = scanHeadLikeTheSdk(html)
    const wanted = collapseWhitespace(subject)
    if (subjectOf(title ? html.slice(title.textStart, title.textEnd) : '') === wanted) {
        return html
    }
    const text = escapeTitleText(wanted)
    if (title) {
        return splice(html, title.textStart, title.textEnd, text)
    }
    return insertIntoHead(html, head, `<title>${text}</title>`)
}

function withPreheader(html: string, preheader: string): string {
    const { title, preheader: existing, ...head } = scanHeadLikeTheSdk(html)
    if (existing?.value === preheader) {
        return html
    }
    if (!preheader.trim()) {
        return withoutPreheaders(html)
    }
    const tag = preheaderTag(preheader)
    if (existing) {
        return splice(html, existing.start, existing.end, tag)
    }
    if (title) {
        return splice(html, title.end, title.end, tag)
    }
    return insertIntoHead(html, head, tag)
}

function withoutPreheaders(html: string): string {
    const kept: string[] = []
    let keptFrom = 0
    for (const { start, end } of scanHeadLikeTheSdk(html).preheaders) {
        kept.push(html.slice(keptFrom, start))
        keptFrom = end
    }
    kept.push(html.slice(keptFrom))
    return kept.join('')
}

function insertIntoHead(html: string, head: HeadScan, markup: string): string {
    if (head.headOpenEnd !== undefined) {
        return splice(html, head.headOpenEnd, head.headOpenEnd, markup)
    }
    const position = head.htmlOpenEnd ?? head.doctypeEnd ?? 0
    return splice(html, position, position, `<head>${markup}</head>`)
}

function splice(html: string, start: number, end: number, replacement: string): string {
    return html.slice(0, start) + replacement + html.slice(end)
}

function scanHeadLikeTheSdk(html: string): HeadScan {
    const context: HeadScanContext = { html, scan: { preheaders: [] }, titleCanClose: true }
    let position = html.indexOf('<')
    while (position !== -1) {
        const next = scanMarkupAt(context, position)
        if (next === undefined) {
            break
        }
        position = html.indexOf('<', next)
    }
    return context.scan
}

function scanMarkupAt(context: HeadScanContext, position: number): number | undefined {
    if (context.html.startsWith(COMMENT_START, position)) {
        return endOfComment(context.html, position)
    }
    if (matchesAt(TAG_NAME, context.html, position)) {
        return scanTitleOrMetaTag(context, position)
    }
    recordDocumentOpenings(context, position)
    return position + 1
}

function endOfComment(html: string, position: number): number | undefined {
    const commentEnd = html.indexOf(COMMENT_END, position + COMMENT_START.length)
    return commentEnd === -1 ? undefined : commentEnd + COMMENT_END.length
}

function scanTitleOrMetaTag(context: HeadScanContext, position: number): number | undefined {
    const isTitle = context.html.slice(position + 1, position + 6).toLowerCase() === 'title'
    const tag = isTitle ? TITLE_OPEN : META_TAG
    if (!matchesAt(tag, context.html, position)) {
        return undefined
    }
    return isTitle ? scanTitle(context, position, tag.lastIndex) : scanMeta(context, position, tag.lastIndex)
}

function scanTitle(context: HeadScanContext, start: number, textStart: number): number {
    if (!context.titleCanClose) {
        return textStart
    }
    TITLE_CLOSE.lastIndex = textStart
    const close = TITLE_CLOSE.exec(context.html)
    if (!close) {
        context.titleCanClose = false
        return textStart
    }
    context.scan.title ??= { start, textStart, textEnd: close.index, end: TITLE_CLOSE.lastIndex }
    return TITLE_CLOSE.lastIndex
}

function scanMeta(context: HeadScanContext, start: number, end: number): number {
    const value = preheaderOf(context.html.slice(start, end))
    if (value !== undefined) {
        const preheader = { start, end, value }
        context.scan.preheaders.push(preheader)
        context.scan.preheader ??= preheader
    }
    return end
}

function recordDocumentOpenings({ html, scan }: HeadScanContext, position: number): void {
    scan.headOpenEnd ??= endOfMatchAt(HEAD_OPEN, html, position)
    scan.htmlOpenEnd ??= endOfMatchAt(HTML_OPEN, html, position)
    scan.doctypeEnd ??= endOfMatchAt(DOCTYPE, html, position)
}

function matchesAt(pattern: RegExp, html: string, position: number): boolean {
    pattern.lastIndex = position
    return pattern.test(html)
}

function endOfMatchAt(pattern: RegExp, html: string, position: number): number | undefined {
    return matchesAt(pattern, html, position) ? pattern.lastIndex : undefined
}

function preheaderOf(metaTag: string): string | undefined {
    const attributes = attributesOf(metaTag)
    return attributes.get('name')?.toLowerCase() === 'preheader'
        ? decodeCharacterReferences(attributes.get('content') ?? '')
        : undefined
}

function attributesOf(tag: string): Map<string, string> {
    const attributes = new Map<string, string>()
    for (const [, name, doubleQuoted, singleQuoted, unquoted] of tag.slice('<meta'.length).matchAll(ATTRIBUTE)) {
        attributes.set(name.toLowerCase(), doubleQuoted ?? singleQuoted ?? unquoted ?? '')
    }
    return attributes
}

function decodeCharacterReferences(value: string): string {
    return value.replace(CHARACTER_REFERENCE, (reference, decimal, hex, named) => {
        if (named) {
            return NAMED_CHARACTERS[named]
        }
        const codePoint = decimal ? parseInt(decimal, 10) : parseInt(hex, 16)
        return codePoint > 0 && codePoint <= 0x10ffff ? String.fromCodePoint(codePoint) : reference
    })
}

function subjectOf(title: string): string {
    return collapseWhitespace(decodeCharacterReferences(title))
}

function collapseWhitespace(value: string): string {
    return value.replace(/[\t\n\f\r ]+/g, ' ').trim()
}

function escapeTitleText(subject: string): string {
    return mapLiquidAndText(
        subject,
        (liquid) => keepCharacterReferences(liquid).replace(TITLE_CLOSE_START, '&lt;'),
        (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    )
}

function keepCharacterReferences(liquid: string): string {
    return liquid.replace(CHARACTER_REFERENCE_START, '&amp;')
}

function preheaderTag(preheader: string): string {
    const liquid = (preheader.match(LIQUID) ?? []).join('')
    const quote = liquid.includes('"') && !liquid.includes("'") ? "'" : '"'
    const escapedQuote = quote === '"' ? '&quot;' : '&#39;'
    const escape = (text: string): string => text.replace(/&/g, '&amp;').replaceAll(quote, escapedQuote)
    const content = liquid.includes(quote)
        ? escape(preheader)
        : mapLiquidAndText(preheader, keepCharacterReferences, escape)
    return `<meta name="preheader" content=${quote}${content}${quote}>`
}

function mapLiquidAndText(
    value: string,
    mapLiquid: (liquid: string) => string,
    mapText: (text: string) => string
): string {
    let mapped = ''
    let textStart = 0
    for (const liquid of value.matchAll(LIQUID)) {
        mapped += mapText(value.slice(textStart, liquid.index)) + mapLiquid(liquid[0])
        textStart = liquid.index + liquid[0].length
    }
    return mapped + mapText(value.slice(textStart))
}
