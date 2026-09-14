import type { Nodes } from 'mdast'
import { fromMarkdown } from 'mdast-util-from-markdown'

const OBJECT_TAG_KINDS = new Set([
    'insight',
    'hogql',
    'dashboard',
    'error',
    'replay',
    'flag',
    'experiment',
    'survey',
    'ticket',
    'report',
    'trace',
    'eval',
    'event',
    'cohort',
    'action',
    'person',
    'session-replay',
    'recording',
    'feature-flag',
    'feature_flag',
    'sql',
])

const OPEN_TAG = /<([a-z][\w-]*)((?:\s+[a-z][\w-]*\s*=\s*"[^"]*")*)\s*(\/?)>/g
const ATTRIBUTE = /([a-z][\w-]*)\s*=\s*"([^"]*)"/g
const XML_ENTITIES: Record<string, string> = {
    '&quot;': '"',
    '&apos;': "'",
    '&lt;': '<',
    '&gt;': '>',
    '&amp;': '&',
}

function tagLabel(kind: string, rawAttributes: string, body: string): string {
    const attributes = Object.fromEntries(
        Array.from(rawAttributes.matchAll(ATTRIBUTE), ([, name, value]) => [
            name,
            value.replace(/&(?:quot|apos|lt|gt|amp);/g, (entity) => XML_ENTITIES[entity]),
        ])
    )
    return (
        attributes.title?.trim() ||
        (kind === 'hogql' || kind === 'sql' ? attributes.label?.trim() || 'SQL query' : body.trim())
    )
}

function flattenSegment(segment: string): string {
    const pieces: string[] = []
    const closers = new Map<string, RegExpExecArray | null>()
    let cursor = 0
    for (const opener of segment.matchAll(OPEN_TAG)) {
        const [, kind, attributes, selfClosing] = opener
        if (opener.index < cursor || !OBJECT_TAG_KINDS.has(kind)) {
            continue
        }
        let end = opener.index + opener[0].length
        let body = ''
        if (!selfClosing) {
            let closer = closers.get(kind)
            if (closer === undefined || (closer !== null && closer.index < end)) {
                const closingTag = new RegExp(`</${kind}\\s*>`, 'g')
                closingTag.lastIndex = end
                closer = closingTag.exec(segment)
                closers.set(kind, closer)
            }
            if (!closer) {
                continue
            }
            body = segment.slice(end, closer.index)
            end = closer.index + closer[0].length
        }
        pieces.push(segment.slice(cursor, opener.index), tagLabel(kind, attributes, body))
        cursor = end
    }
    pieces.push(segment.slice(cursor))
    return pieces.join('')
}

export function flattenObjectTags(text: string): string {
    const pieces: string[] = []
    let cursor = 0
    function preserveCode(node: Nodes): void {
        if (node.type === 'code' || node.type === 'inlineCode') {
            const start = node.position?.start.offset
            const end = node.position?.end.offset
            if (start !== undefined && end !== undefined) {
                pieces.push(flattenSegment(text.slice(cursor, start)), text.slice(start, end))
                cursor = end
            }
        } else if ('children' in node) {
            node.children.forEach(preserveCode)
        }
    }
    preserveCode(fromMarkdown(text))
    pieces.push(flattenSegment(text.slice(cursor)))
    return pieces.join('')
}
