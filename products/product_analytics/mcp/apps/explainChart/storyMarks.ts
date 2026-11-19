export type StoryMarkKind = 'value' | 'date' | 'name'

export interface StoryTextPart {
    text: string
    kind: StoryMarkKind | null
}

const OPEN = '⟦'
const CLOSE = '⟧'
const CODES: Record<string, StoryMarkKind> = { v: 'value', d: 'date', n: 'name' }
// A stretch that the page marked, or one that the model marked with double asterisks.
const MARKED = new RegExp(`${OPEN}([vdn]):([^${CLOSE}]*)${CLOSE}|\\*\\*([^*]+)\\*\\*`, 'g')
const MONTH = /\b(January|February|March|April|May|June|July|August|September|October|November|December)\b/

export function mark(kind: StoryMarkKind, text: string): string {
    return `${OPEN}${kind[0]}:${text.replaceAll(OPEN, '').replaceAll(CLOSE, '')}${CLOSE}`
}

// The model only says that a stretch matters, so what it is comes from how it reads.
function kindOf(text: string): StoryMarkKind {
    if (MONTH.test(text) && /\d/.test(text)) {
        return 'date'
    }
    return /^[^\p{L}]*\d/u.test(text) ? 'value' : 'name'
}

export function storyTextParts(text: string): StoryTextPart[] {
    const parts: StoryTextPart[] = []
    let from = 0
    for (const match of text.matchAll(MARKED)) {
        if (match.index > from) {
            parts.push({ text: text.slice(from, match.index), kind: null })
        }
        const [, code, pageText, modelText] = match
        parts.push(
            modelText !== undefined
                ? { text: modelText, kind: kindOf(modelText) }
                : { text: pageText ?? '', kind: (code && CODES[code]) || null }
        )
        from = match.index + match[0].length
    }
    if (from < text.length) {
        parts.push({ text: text.slice(from), kind: null })
    }
    return parts
}

export function markedNames(text: string): string[] {
    return storyTextParts(text).flatMap((part) => (part.kind === 'name' ? [part.text] : []))
}

/** The text without its marks, for a prompt or a label. A name gets quotes there, where no highlight sets it apart. */
export function plainStoryText(text: string): string {
    return storyTextParts(text)
        .map((part) => (part.kind === 'name' ? `"${part.text}"` : part.text))
        .join('')
}
