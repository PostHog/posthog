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

const OBJECT_TAG = /<(\/?)([a-z][\w-]*)(?:\s+[a-z][\w-]*\s*=\s*(?:"[^"]*"|'[^']*'))*\s*(\/?)>/g

export function stripObjectTags(text: string): string {
    const pieces: string[] = []
    let cursor = 0
    let activeKind: string | null = null
    let depth = 0
    for (const tag of text.matchAll(OBJECT_TAG)) {
        const [, closing, kind, selfClosing] = tag
        if (!OBJECT_TAG_KINDS.has(kind)) {
            continue
        }
        if (activeKind !== null) {
            if (kind === activeKind) {
                if (closing) {
                    depth--
                } else if (!selfClosing) {
                    depth++
                }
                if (depth === 0) {
                    activeKind = null
                    cursor = tag.index + tag[0].length
                }
            }
            continue
        }
        pieces.push(text.slice(cursor, tag.index))
        cursor = tag.index + tag[0].length
        if (!closing && !selfClosing) {
            activeKind = kind
            depth = 1
        }
    }
    if (activeKind === null) {
        pieces.push(text.slice(cursor))
    }
    return pieces.join('')
}
