export type MarkdownBlock =
    | { kind: 'heading'; level: number; text: string }
    | { kind: 'paragraph'; text: string }
    | { kind: 'list'; ordered: boolean; items: string[] }
    | { kind: 'code'; text: string }
    | { kind: 'table'; header: string[]; rows: string[][] }

const LIST_ITEM = /^\s*(?:[-*+]|(\d+)[.)])\s+(.*)$/
const HEADING = /^(#{1,6})\s+(.*)$/
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/
const FENCE = /^\s*```/
// Underscore emphasis is left out on purpose: answers name events and properties such as
// `purchase_completed`, and a `_..._` rule would italicize the middle of those names.
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*\*)/g
const LINK = /^\[([^\]]+)\]\(([^)\s]+)\)$/

function splitRow(line: string): string[] {
    return line
        .trim()
        .replace(/^\|/, '')
        .replace(/\|$/, '')
        .split('|')
        .map((cell) => cell.trim())
}

function startsBlock(line: string, next: string | undefined): boolean {
    return (
        FENCE.test(line) ||
        HEADING.test(line) ||
        LIST_ITEM.test(line) ||
        (line.includes('|') && next !== undefined && TABLE_SEPARATOR.test(next))
    )
}

export function parseMarkdown(source: string): MarkdownBlock[] {
    const lines = source.replace(/\r\n/g, '\n').split('\n')
    const blocks: MarkdownBlock[] = []
    let i = 0
    while (i < lines.length) {
        const line = lines[i] ?? ''
        if (!line.trim()) {
            i++
            continue
        }
        if (FENCE.test(line)) {
            const body: string[] = []
            i++
            while (i < lines.length && !FENCE.test(lines[i] ?? '')) {
                body.push(lines[i] ?? '')
                i++
            }
            i++
            blocks.push({ kind: 'code', text: body.join('\n') })
            continue
        }
        const heading = HEADING.exec(line)
        if (heading) {
            blocks.push({ kind: 'heading', level: heading[1]?.length ?? 1, text: heading[2] ?? '' })
            i++
            continue
        }
        if (line.includes('|') && TABLE_SEPARATOR.test(lines[i + 1] ?? '')) {
            const header = splitRow(line)
            const rows: string[][] = []
            i += 2
            while (i < lines.length && (lines[i] ?? '').includes('|') && (lines[i] ?? '').trim()) {
                rows.push(splitRow(lines[i] ?? ''))
                i++
            }
            blocks.push({ kind: 'table', header, rows })
            continue
        }
        const first = LIST_ITEM.exec(line)
        if (first) {
            const ordered = first[1] !== undefined
            const items: string[] = []
            while (i < lines.length) {
                const current = lines[i] ?? ''
                const item = LIST_ITEM.exec(current)
                if (item && (item[1] !== undefined) === ordered) {
                    items.push(item[2] ?? '')
                } else if (items.length > 0 && current.trim() && /^\s{2,}/.test(current)) {
                    items[items.length - 1] += ` ${current.trim()}`
                } else {
                    break
                }
                i++
            }
            blocks.push({ kind: 'list', ordered, items })
            continue
        }
        const paragraph: string[] = [line.trim()]
        i++
        while (i < lines.length && (lines[i] ?? '').trim() && !startsBlock(lines[i] ?? '', lines[i + 1])) {
            paragraph.push((lines[i] ?? '').trim())
            i++
        }
        blocks.push({ kind: 'paragraph', text: paragraph.join(' ') })
    }
    return blocks
}

export type InlineToken =
    | { kind: 'text'; text: string }
    | { kind: 'strong'; children: InlineToken[] }
    | { kind: 'em'; children: InlineToken[] }
    | { kind: 'code'; text: string }
    | { kind: 'link'; url: string; children: InlineToken[] }

function isSafeUrl(url: string): boolean {
    return /^https?:\/\//i.test(url)
}

/** Splits a line into inline tokens. A link to anything other than http or https becomes plain text. */
export function parseInline(text: string): InlineToken[] {
    const tokens: InlineToken[] = []
    let last = 0
    for (const match of text.matchAll(INLINE)) {
        const token = match[0]
        const index = match.index ?? 0
        if (index > last) {
            tokens.push({ kind: 'text', text: text.slice(last, index) })
        }
        if (token.startsWith('**')) {
            tokens.push({ kind: 'strong', children: parseInline(token.slice(2, -2)) })
        } else if (token.startsWith('`')) {
            tokens.push({ kind: 'code', text: token.slice(1, -1) })
        } else if (token.startsWith('[')) {
            const [, label = '', url = ''] = LINK.exec(token) ?? []
            tokens.push(
                isSafeUrl(url) ? { kind: 'link', url, children: parseInline(label) } : { kind: 'text', text: label }
            )
        } else {
            tokens.push({ kind: 'em', children: parseInline(token.slice(1, -1)) })
        }
        last = index + token.length
    }
    if (last < text.length) {
        tokens.push({ kind: 'text', text: text.slice(last) })
    }
    return tokens
}
