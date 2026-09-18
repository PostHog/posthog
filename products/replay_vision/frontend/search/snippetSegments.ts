import { escapeRegex } from 'lib/utils/actions'

export interface SnippetSegment {
    text: string
    highlighted: boolean
}

const STOPWORDS = new Set([
    'the',
    'and',
    'for',
    'was',
    'were',
    'with',
    'that',
    'this',
    'from',
    'into',
    'after',
    'about',
    'their',
    'have',
    'has',
    'who',
])

// Past what the two-line clamp shows.
const MAX_LEAD_CHARS = 120
const WINDOW_CONTEXT_CHARS = 40

/** Split a snippet into segments, marking whole words that start with a query term ("click"
 * also marks "clicking"). A match deep in the text is windowed in behind a leading ellipsis. */
export function snippetSegments(text: string, query: string): SnippetSegment[] {
    // Non-ASCII words are dropped whole: fragmenting "usuário" to "usu" would highlight unrelated words.
    const terms = Array.from(
        new Set(
            query
                .toLowerCase()
                .split(/[^\p{L}\p{N}]+/u)
                .filter((term) => /^[a-z0-9]{3,}$/.test(term) && !STOPWORDS.has(term))
        )
    )
    if (terms.length === 0) {
        return [{ text, highlighted: false }]
    }
    const pattern = new RegExp(`\\b(?:${terms.map(escapeRegex).join('|')})[a-z0-9]*`, 'gi')

    const segments: SnippetSegment[] = []
    let display = text
    const firstMatchIndex = text.search(pattern)
    if (firstMatchIndex > MAX_LEAD_CHARS) {
        let start = firstMatchIndex - WINDOW_CONTEXT_CHARS
        const wordBoundary = text.indexOf(' ', start)
        if (wordBoundary !== -1 && wordBoundary < firstMatchIndex) {
            start = wordBoundary + 1
        }
        display = text.slice(start)
        segments.push({ text: '… ', highlighted: false })
    }

    let consumedTo = 0
    for (const match of display.matchAll(pattern)) {
        if (match.index > consumedTo) {
            segments.push({ text: display.slice(consumedTo, match.index), highlighted: false })
        }
        segments.push({ text: match[0], highlighted: true })
        consumedTo = match.index + match[0].length
    }
    if (consumedTo < display.length) {
        segments.push({ text: display.slice(consumedTo), highlighted: false })
    }
    return segments
}
