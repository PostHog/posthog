/** Inline `(event_id <hash>)` marker the model emits in free-text fields. Mirrors backend's `_EVENT_ID_CITATION_RE`; keep in sync. */
const EVENT_ID_PATTERN = /\(event_id ([0-9a-f]{16})\)/gi

export type CitationPart = { type: 'text'; value: string } | { type: 'citation'; timestampMs: number; uuid?: string }

/**
 * Parse free-text from a scanner's model output into a sequence of plain-text segments and citation chips,
 * resolving inline `(event_id <hash>)` markers against the observation's `event_id_mapping`. Unresolved markers
 * are stripped so they never reach the UI as raw text.
 */
export function parseCitedText(
    text: string | null | undefined,
    mapping: Record<string, unknown> | null | undefined
): CitationPart[] {
    if (!text) {
        return []
    }
    const map = mapping ?? {}
    const parts: CitationPart[] = []
    let lastIndex = 0
    EVENT_ID_PATTERN.lastIndex = 0
    let match: RegExpExecArray | null
    while ((match = EVENT_ID_PATTERN.exec(text)) !== null) {
        const [full, hash] = match
        const citation = map[hash.toLowerCase()] as { uuid?: string; timestamp_ms?: number } | undefined
        if (match.index > lastIndex) {
            parts.push({ type: 'text', value: text.slice(lastIndex, match.index) })
        }
        if (citation && typeof citation.timestamp_ms === 'number') {
            parts.push({ type: 'citation', timestampMs: citation.timestamp_ms, uuid: citation.uuid })
        }
        // Unresolved citations are silently dropped — raw markers must never reach the UI.
        lastIndex = match.index + full.length
    }
    if (lastIndex < text.length) {
        parts.push({ type: 'text', value: text.slice(lastIndex) })
    }
    return parts
}

export function formatSessionOffset(ms: number): string {
    const totalSeconds = Math.max(0, Math.floor(ms / 1000))
    const h = Math.floor(totalSeconds / 3600)
    const m = Math.floor((totalSeconds % 3600) / 60)
    const s = totalSeconds % 60
    if (h > 0) {
        return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
    }
    return `${m}:${s.toString().padStart(2, '0')}`
}
