type Piece = { kind: 'text' | 'liquid'; value: string }

interface HtmlTag {
    name: string
    closing: boolean
    /** Attribute source by lowercase name. Entities and Liquid are still as written. */
    attributes: Record<string, string>
    /** Its Liquid tags and the value of each `href`, in order, for an address that depends on a condition. */
    flow: string
    end: number
}

const RAW_OPEN = /\{%-?\s*raw\s*-?%\}/y
const RAW_CLOSE = /\{%-?\s*endraw\s*-?%\}/g
const RAW_CLOSE_HERE = new RegExp(RAW_CLOSE.source, 'y')
/** Marks a set of unclosed starts once the rest of the html has no end of a raw block. */
const NO_RAW_CLOSE = -1
const TAG_START = /<(\/?)([a-z][^\s/>{]*)/iy
const TEXT_END = /[<{]/g
const LIQUID_TAG_NAME = /^\{%-?\s*(\w+)/
const LITERAL_LIQUID = /\{[{%][\s\S]*?(?:\}\}+|%\}|$)/g
const ENDRAW_IN_TEXT = /\{%(?=-?\s*endraw\b)/g

/** A `<br>` until the end, because two in a row are how an email leaves a line empty. */
const LINE_BREAK = '\v'

const HIDDEN_ELEMENTS = new Set(['style', 'script', 'title'])
const LINE_ELEMENTS = new Set(['p', 'div', 'tr', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
const CELL_ELEMENTS = new Set(['td', 'th'])
const LIQUID_BLOCKS = new Set(['if', 'unless', 'case', 'for', 'tablerow', 'capture', 'comment'])
const LIQUID_BRANCHES = new Set(['else', 'elsif', 'when'])
/** Tags that only set something up, so they matter even when the markup around them isn't text. */
const LIQUID_SETUP = new Set(['assign', 'capture', 'liquid'])
const LIQUID_CHANGES_VALUE = new Set([...LIQUID_SETUP, 'increment', 'decrement'])
const LIQUID_PRINTS = new Set(['cycle', 'increment', 'decrement', 'echo', 'include', 'render', 'unsubscribe_url'])

/** Filters that make a value safe inside html. In plain text they would print entities, and break a URL. */
const HTML_ESCAPE_FILTERS =
    /(?:\s*\|\s*(?:escape|escape_once|raw|replace:\s*"[=`]",\s*"&(?:amp;)?#x(?:3D|60);"))+\s*(?=-?\}\}$)/

function execAt(pattern: RegExp, text: string, position: number): RegExpExecArray | null {
    pattern.lastIndex = position
    return pattern.exec(text)
}

function holdsRawClose(text: string): boolean {
    return text.search(RAW_CLOSE) !== -1
}

/**
 * Where the Liquid tag that starts here ends, read the way LiquidJS does: a quoted string can hold a delimiter.
 * `unclosed` collects the starts that have no end, so a later search from or through one stops there.
 */
function liquidEnd(html: string, start: number, unclosed: Set<number>): number | null {
    const close = html[start + 1] === '{' ? '}}' : html[start + 1] === '%' ? '%}' : null
    if (html[start] !== '{' || !close || unclosed.has(start)) {
        return null
    }
    const starts = [start]
    let quote = ''
    for (let at = start + 2; at < html.length; at++) {
        if (quote) {
            if (html[at] === '\\') {
                at++
            } else if (html[at] === quote) {
                quote = ''
            }
        } else if (html[at] === '"' || html[at] === "'") {
            quote = html[at]
        } else if (html.startsWith(close, at)) {
            return at + 2
        } else if (html[at] === '{' && html[at + 1] === html[start + 1]) {
            if (unclosed.has(at)) {
                break
            }
            starts.push(at)
        }
    }
    starts.forEach((position) => unclosed.add(position))
    return null
}

/** The end of a raw block that starts here, or of the one Liquid tag. */
function liquidUnitEnd(html: string, start: number, unclosed: Set<number>): number | null {
    if (execAt(RAW_OPEN, html, start) && !unclosed.has(NO_RAW_CLOSE)) {
        const close = execAt(RAW_CLOSE, html, RAW_OPEN.lastIndex)
        if (close) {
            return RAW_CLOSE.lastIndex
        }
        unclosed.add(NO_RAW_CLOSE)
    }
    return liquidEnd(html, start, unclosed)
}

/** Reads a tag with Liquid in mind, because Liquid runs first: a quote inside one doesn't end an attribute. */
function readTag(html: string, start: number, inRaw: boolean, unclosed: Set<number>): HtmlTag | null {
    const match = execAt(TAG_START, html, start)
    if (!match) {
        return null
    }
    const tag: HtmlTag = {
        name: match[2].toLowerCase(),
        closing: !!match[1],
        attributes: {},
        flow: '',
        end: html.length,
    }
    let at = start + match[0].length
    const skip = (): boolean => {
        const end = !inRaw && html[at] === '{' ? liquidUnitEnd(html, at, unclosed) : null
        if (end === null) {
            return false
        }
        at = end
        return true
    }
    while (at < html.length && html[at] !== '>') {
        if (/[\s/]/.test(html[at])) {
            at++
            continue
        }
        const liquidStart = at
        if (skip()) {
            tag.flow += liquidTagsIn(html.slice(liquidStart, at))
            continue
        }
        const nameStart = at
        do {
            at++
        } while (at < html.length && !/[\s/>=]/.test(html[at]))
        const name = html.slice(nameStart, at).toLowerCase()
        const equals = /\s*=\s*/y
        if (!execAt(equals, html, at)) {
            continue
        }
        at = equals.lastIndex
        const quote = html[at] === '"' || html[at] === "'" ? html[at++] : ''
        const valueStart = at
        while (at < html.length && (quote ? html[at] !== quote : !/[\s>]/.test(html[at]))) {
            if (!skip()) {
                at++
            }
        }
        // The first one wins, as it does in a browser.
        const value = html.slice(valueStart, at)
        tag.attributes[name] ??= value
        if (name === 'href') {
            tag.flow += value.trim()
        } else if (!inRaw) {
            tag.flow += liquidTagsIn(value)
        }
        at += quote ? 1 : 0
    }
    tag.end = Math.min(at + 1, html.length)
    return tag
}

function decodeEntities(text: string): string {
    if (!text.includes('&')) {
        return text
    }
    const element = document.createElement('textarea')
    element.innerHTML = text
    return element.value
}

/** The Liquid tags and the text of a string that holds no markup, such as a link's address. */
function piecesOf(source: string, inRaw: boolean): Piece[] {
    if (inRaw) {
        return [{ kind: 'text', value: decodeEntities(source.replace(RAW_CLOSE, '')) }]
    }
    const pieces: Piece[] = []
    const unclosed = new Set<number>()
    let at = 0
    while (at < source.length) {
        const raw = execAt(RAW_OPEN, source, at)
        const end = liquidUnitEnd(source, at, unclosed)
        if (end === null) {
            const next = source.indexOf('{', at + 1)
            const stop = next === -1 ? source.length : next
            pieces.push({ kind: 'text', value: decodeEntities(source.slice(at, stop)) })
            at = stop
            continue
        }
        const unit = source.slice(at, end)
        // A raw block that closes further on keeps the rest literal.
        if (raw && end === at + raw[0].length) {
            pieces.push({ kind: 'text', value: decodeEntities(source.slice(end)) })
            break
        }
        pieces.push(
            raw
                ? { kind: 'text', value: decodeEntities(unit.slice(raw[0].length).replace(RAW_CLOSE, '')) }
                : liquidPiece(unit)
        )
        at = end
    }
    return pieces
}

function liquidPiece(tag: string): Piece {
    return { kind: 'liquid', value: tag.startsWith('{{') ? tag.replace(HTML_ESCAPE_FILTERS, ' ') : tag }
}

/** The Liquid tags of a string that print nothing, without the text between them. */
function liquidTagsIn(source: string): string {
    return piecesOf(source, false)
        .filter((piece) => {
            const name = liquidTagName(piece)
            return !!name && !LIQUID_PRINTS.has(name)
        })
        .map((piece) => piece.value)
        .join('')
}

function liquidTagName(piece: Piece): string | null {
    return piece.kind === 'liquid' ? (LIQUID_TAG_NAME.exec(piece.value)?.[1] ?? null) : null
}

/** Whether the Liquid in a label sets a value, so an address written after it could read another one. */
export function changesLiquidValue(source: string): boolean {
    return piecesOf(source, false).some((piece) => LIQUID_CHANGES_VALUE.has(liquidTagName(piece) ?? ''))
}

/** Whether the pieces start and end in the same branch of every condition and loop. */
function staysInOneBranch(pieces: Piece[]): boolean {
    let depth = 0
    for (const piece of pieces) {
        const name = liquidTagName(piece)
        if (!name) {
            continue
        }
        if (LIQUID_BLOCKS.has(name)) {
            depth++
        } else if (name.startsWith('end') && LIQUID_BLOCKS.has(name.slice(3))) {
            depth--
        } else if (LIQUID_BRANCHES.has(name) && depth === 0) {
            return false
        }
        if (depth < 0) {
            return false
        }
    }
    return depth === 0
}

/** What Liquid in markup nobody reads still does: it can set a variable, or open a condition that ends further on. */
function tagsToKeep(hidden: string): Piece[] {
    let captures = 0
    const tags = piecesOf(hidden, false).filter((piece) => {
        const name = liquidTagName(piece)
        captures += name === 'capture' ? 1 : name === 'endcapture' ? -1 : 0
        return captures > 0 || (!!name && !LIQUID_PRINTS.has(name))
    })
    return staysInOneBranch(tags) && !tags.some((piece) => LIQUID_SETUP.has(liquidTagName(piece) ?? '')) ? [] : tags
}

function leavesRawOpen(text: string): boolean {
    let open = false
    for (const [, end] of text.matchAll(/\{%-?\s*(end)?raw\s*-?%\}/g)) {
        open = !end
    }
    return open
}

function textOf(pieces: Piece[]): string {
    let text = ''
    for (let index = 0; index < pieces.length; index++) {
        const piece = pieces[index]
        if (piece.kind === 'liquid') {
            // A brace in the text right before a tag would become part of the tag.
            text += `${text.endsWith('{') ? ' ' : ''}${piece.value}`
            continue
        }
        // Text from several elements can only form a tag once it's joined, so it's joined before it's checked.
        let run = piece.value
        while (pieces[index + 1]?.kind === 'text') {
            run += pieces[++index].value
        }
        text += run.replace(
            LITERAL_LIQUID,
            (literal) => `{% raw %}${literal.replace(ENDRAW_IN_TEXT, '{ %')}{% endraw %}`
        )
    }
    return text
}

interface LinkAddress {
    pieces: Piece[]
    text: string
}

function linkAddress(tag: HtmlTag, inRaw: boolean): LinkAddress | null {
    const href = tag.attributes.href?.trim()
    if (!href) {
        return null
    }
    const flow = piecesOf(tag.flow, inRaw)
    const toHref = flow.slice(
        0,
        flow.findIndex((piece) => !liquidTagName(piece))
    )
    const hrefPieces = piecesOf(href, inRaw)
    const pieces = staysInOneBranch(toHref) && staysInOneBranch(hrefPieces) ? hrefPieces : flow
    const text = textOf(pieces).trim()
    return !text || /^(#|(javascript|vbscript|data):)/i.test(text) ? null : { pieces, text }
}

/**
 * The plain text of an email's html, with the address of every link after its text.
 *
 * It reads the html from start to end instead of parsing it, because a browser's parser moves text out of table rows:
 * that would take a Liquid tag out of the rows or the raw block it belongs to. Every Liquid tag stays in its order, so
 * the text renders whenever the html does.
 */
export function htmlToEmailText(html: string, { imageText = true }: { imageText?: boolean } = {}): string {
    const out: Piece[] = []
    const unclosed = new Set<number>()
    let link: { start: number; address: LinkAddress } | null = null
    let inRaw = false
    let lineEmpty = true
    let at = 0

    const addText = (value: string): void => {
        if (!value) {
            return
        }
        out.push({ kind: 'text', value })
        if (/[\n\v][ \t]*$/.test(value)) {
            lineEmpty = true
        } else if (value.trim()) {
            lineEmpty = false
        }
    }
    const skipHidden = (hidden: string): void => {
        if (inRaw) {
            inRaw = !holdsRawClose(hidden)
            return
        }
        out.push(...tagsToKeep(hidden))
        inRaw = leavesRawOpen(hidden)
    }
    const closeLink = (): void => {
        if (!link) {
            return
        }
        const { start, address } = link
        link = null
        const inner = out.slice(start)
        const changesValue = inner.some((piece) => LIQUID_CHANGES_VALUE.has(liquidTagName(piece) ?? ''))
        if (changesValue || !staysInOneBranch(inner)) {
            // The address belongs where the link opens: in that branch, and with the values set there.
            out.splice(start, 0, ...address.pieces, { kind: 'text', value: ' ' })
            return
        }
        const label = textOf(inner).replace(/\s+/g, ' ').trim()
        if (!label) {
            out.push({ kind: 'text', value: ' ' }, ...address.pieces, { kind: 'text', value: ' ' })
            lineEmpty = false
        } else if (label !== address.text && label !== address.text.replace(/^(mailto|tel):/i, '')) {
            out.push({ kind: 'text', value: ' (' }, ...address.pieces, { kind: 'text', value: ')' })
        }
    }
    const startLine = (): void => {
        if (!lineEmpty) {
            addText('\n')
        }
    }
    const onTag = (tag: HtmlTag): void => {
        const { name, closing } = tag
        if (name === 'a') {
            closeLink()
            const flow = piecesOf(tag.flow, inRaw)
            if (!staysInOneBranch(flow)) {
                // Part of the tag is in a branch that goes on after it, so its addresses go where they are.
                out.push(...flow, { kind: 'text', value: ' ' })
                return
            }
            const address = closing ? null : linkAddress(tag, inRaw)
            link = address ? { start: out.length, address } : null
        } else if ((name === 'img' || name === 'area') && !closing) {
            const address =
                name === 'area' && staysInOneBranch(piecesOf(tag.flow, inRaw)) ? linkAddress(tag, inRaw) : null
            const altPieces = imageText ? piecesOf(tag.attributes.alt ?? '', inRaw) : []
            // A condition that ends outside the alt text can't be written from the alt text alone.
            const alt = staysInOneBranch(altPieces) ? altPieces : []
            out.push(...alt)
            lineEmpty = lineEmpty && !alt.length
            if (address) {
                const hasAlt = !!textOf(alt).trim()
                addText(hasAlt ? ' (' : ' ')
                out.push(...address.pieces)
                addText(hasAlt ? ')\n' : '\n')
            }
        } else if (name === 'br') {
            addText(LINE_BREAK)
        } else if (closing && LINE_ELEMENTS.has(name)) {
            addText('\n')
        } else if (LINE_ELEMENTS.has(name) || name === 'table') {
            startLine()
        } else if (closing && CELL_ELEMENTS.has(name)) {
            addText(' ')
        }
    }

    while (at < html.length) {
        if (html[at] === '{') {
            const rawClose = inRaw ? execAt(RAW_CLOSE_HERE, html, at) : null
            const rawOpen = inRaw ? null : execAt(RAW_OPEN, html, at)
            const end = inRaw ? null : liquidEnd(html, at, unclosed)
            if (rawClose) {
                inRaw = false
                at += rawClose[0].length
                continue
            }
            if (rawOpen) {
                inRaw = true
                at += rawOpen[0].length
                continue
            }
            if (end !== null) {
                const piece = liquidPiece(html.slice(at, end))
                out.push(piece)
                lineEmpty = lineEmpty && !piece.value.startsWith('{{')
                at = end
                continue
            }
        }
        if (html.startsWith('<!--', at)) {
            const close = html.indexOf('-->', at + 2)
            const end = close === -1 ? html.length : close + 3
            skipHidden(html.slice(at, end))
            at = end
            continue
        }
        if (html[at] === '<' && /[!?]/.test(html[at + 1] ?? '')) {
            const close = html.indexOf('>', at)
            at = close === -1 ? html.length : close + 1
            continue
        }
        const tag: HtmlTag | null = html[at] === '<' ? readTag(html, at, inRaw, unclosed) : null
        if (tag) {
            // A condition can open inside a tag and close after it.
            const keptByLink = tag.name === 'a' && !staysInOneBranch(piecesOf(tag.flow, inRaw))
            out.push(...(inRaw || keptByLink ? [] : tagsToKeep(html.slice(at, tag.end))))
            onTag(tag)
            inRaw = inRaw && !holdsRawClose(html.slice(at, tag.end))
            at = tag.end
            if (HIDDEN_ELEMENTS.has(tag.name) && !tag.closing) {
                const close = execAt(new RegExp(`</${tag.name}[^>]*>`, 'gi'), html, at)
                const end = close ? close.index : html.length
                skipHidden(html.slice(at, end))
                at = close ? end + close[0].length : end
            }
            continue
        }
        const end = execAt(TEXT_END, html, at + 1)?.index ?? html.length
        addText(decodeEntities(html.slice(at, end)).replaceAll(LINE_BREAK, ' '))
        at = end
    }
    closeLink()

    return textOf(out)
        .replace(/[ \t]+/g, ' ')
        .replace(/ ?[\n\v][ \n\v]*/g, (lines) => (lines.split(LINE_BREAK).length > 2 ? '\n\n' : '\n'))
        .trim()
}

/**
 * Whether a text is only the words of this html, as a provider or an importer writes it. Spacing, conditions and
 * filters differ between writers, so they don't count.
 */
export function isTextOfHtml(text: string, html: string): boolean {
    const words = (value: string): string =>
        value
            .replace(/\{%[\s\S]*?%\}/g, '')
            .replace(/\s*\|[^{}]*\}\}/g, '}}')
            .replace(/\((?:mailto:|tel:|#)[^()]*\)|[()]/g, '')
            .replace(/[\s\u00ad\u034f\u200b-\u200f\u2060\ufeff]+/g, '')
    return [true, false].some((imageText) => words(htmlToEmailText(html, { imageText })) === words(text))
}
