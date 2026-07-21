// `uuid` is legacy (only old event-uuid citations carry it). Timestamp citations use `timestamp_ms` alone.
export type Segment = { kind: 'text'; value: string } | { kind: 'chip'; timestamp_ms: number; uuid?: string }

export function isSegment(value: unknown): value is Segment {
    if (!value || typeof value !== 'object') {
        return false
    }
    const candidate = value as Partial<Segment>
    if (candidate.kind === 'text') {
        return typeof (candidate as { value?: unknown }).value === 'string'
    }
    if (candidate.kind === 'chip') {
        const chip = candidate as Partial<Extract<Segment, { kind: 'chip' }>>
        return typeof chip.timestamp_ms === 'number'
    }
    return false
}

// Matches `(t 123)` and leaked comma-joined variants like `(t 123, 456)` / `(t 12, t 34)`.
// Mirrors the backend's TIMESTAMP_CITATION_RE (backend/temporal/scanners/base.py).
const TIMESTAMP_CITATION_RE = /\s*\(\s*t\s*(\d+(?:\s*,\s*t?\s*\d+)*)\s*\)/g

/** Split leaked `(t <sec>)` markers in plain text into chip segments, one chip per cited second. */
function splitLeakedCitations(text: string): Segment[] {
    const segments: Segment[] = []
    let lastEnd = 0
    for (const match of text.matchAll(TIMESTAMP_CITATION_RE)) {
        const chunk = text.slice(lastEnd, match.index)
        if (chunk) {
            segments.push({ kind: 'text', value: chunk })
        }
        for (const seconds of match[1].match(/\d+/g) ?? []) {
            segments.push({ kind: 'chip', timestamp_ms: parseInt(seconds, 10) * 1000 })
        }
        lastEnd = match.index + match[0].length
    }
    const trailing = text.slice(lastEnd)
    if (trailing) {
        segments.push({ kind: 'text', value: trailing })
    }
    return segments
}

/**
 * Render-ready segments for a cited field: the persisted segments when present (falling back to the plain text
 * otherwise), with any `(t <sec>)` markers the backend missed at scan time split into chips client-side, so
 * observations persisted before a marker variant was parseable still render seekable chips.
 */
export function parseCitedSegments(text: string, segments: unknown): Segment[] {
    const persisted = Array.isArray(segments) ? segments.filter(isSegment) : []
    if (persisted.length === 0) {
        return splitLeakedCitations(text)
    }
    return persisted.flatMap((segment) => (segment.kind === 'text' ? splitLeakedCitations(segment.value) : [segment]))
}
