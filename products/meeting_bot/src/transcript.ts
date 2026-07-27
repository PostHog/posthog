export interface Utterance {
    speaker: string
    text: string
    /** Milliseconds since epoch, taken when the utterance was finalized. */
    at: number
}

export interface TriggerMatch {
    /** Everything the speaker said after the trigger phrase, verbatim. */
    prompt: string
}

/** Wake words that stand in for whatever leads the configured trigger phrase. */
const WAKE_SYNONYMS = new Set(['hey', 'hi', 'hello', 'ok', 'okay', 'yo'])

function normalize(text: string): string {
    return text.toLowerCase().replace(/[^a-z0-9\s]/g, ' ')
}

interface Token {
    word: string
    /** Offset into the original string, so the prompt can be sliced out with its punctuation intact. */
    end: number
}

function tokenize(text: string): Token[] {
    const normalized = normalize(text)
    const tokens: Token[] = []
    const pattern = /[a-z0-9]+/g
    let match: RegExpExecArray | null
    while ((match = pattern.exec(normalized)) !== null) {
        tokens.push({ word: match[0], end: match.index + match[0].length })
    }
    return tokens
}

function editDistance(a: string, b: string): number {
    let previous = Array.from({ length: b.length + 1 }, (_, i) => i)
    for (let i = 1; i <= a.length; i++) {
        const current = [i]
        for (let j = 1; j <= b.length; j++) {
            const substitution = previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)
            current[j] = Math.min(substitution, previous[j] + 1, current[j - 1] + 1)
        }
        previous = current
    }
    return previous[b.length]
}

/**
 * Speech-to-text reliably mangles "posthog" into things like "post hog", "post hoc" and "posthawk",
 * so the brand word is matched by edit distance rather than equality. The allowance scales with length
 * because one substitution in a four-letter word is a much weaker signal than two in an eight-letter one.
 */
function brandTolerance(word: string): number {
    if (word.length <= 4) {
        return 1
    }
    return word.length <= 6 ? 2 : 3
}

function matchesWakeWord(spoken: string, expected: string): boolean {
    if (WAKE_SYNONYMS.has(spoken)) {
        return true
    }
    return editDistance(spoken, expected) <= 1
}

/**
 * Looks for the trigger phrase and returns whatever follows it in the same utterance.
 *
 * The brand word may arrive split across up to three tokens ("post hog", "boss talk"), so candidate
 * matches are built by joining following tokens before comparing.
 */
export function findTrigger(text: string, triggerPhrase: string): TriggerMatch | null {
    const triggerWords = tokenize(triggerPhrase).map((token) => token.word)
    if (triggerWords.length === 0) {
        return null
    }
    const brand = triggerWords[triggerWords.length - 1]
    const wakeWords = triggerWords.slice(0, -1)
    const tokens = tokenize(text)

    for (let start = 0; start + wakeWords.length < tokens.length; start++) {
        const wakeMatches = wakeWords.every((expected, offset) =>
            matchesWakeWord(tokens[start + offset].word, expected)
        )
        if (!wakeMatches) {
            continue
        }

        const brandStart = start + wakeWords.length
        // Every join length is scored and the closest wins, rather than returning the first one inside
        // tolerance. "post" is within tolerance of "posthog" on its own, so stopping early on "hey post hog"
        // would leave "hog" at the front of the question.
        let best: { distance: number; joined: number } | null = null
        for (let joined = 1; joined <= 3 && brandStart + joined <= tokens.length; joined++) {
            const candidate = tokens
                .slice(brandStart, brandStart + joined)
                .map((token) => token.word)
                .join('')
            const distance = editDistance(candidate, brand)
            if (distance <= brandTolerance(brand) && (!best || distance < best.distance)) {
                best = { distance, joined }
            }
        }

        if (best) {
            const promptStart = tokens[brandStart + best.joined - 1].end
            return {
                prompt: text
                    .slice(promptStart)
                    .replace(/^[\s,.:;!?-]+/, '')
                    .trim(),
            }
        }
    }

    return null
}

/**
 * A short rolling window of what has been said, so a question like "and what about last week?" can be
 * answered against the conversation it was asked in.
 */
export class TranscriptBuffer {
    private utterances: Utterance[] = []

    constructor(private readonly windowSeconds: number) {}

    add(utterance: Utterance): void {
        this.utterances.push(utterance)
        this.prune(utterance.at)
    }

    /** Oldest first, formatted for a prompt. */
    context(now: number): string {
        this.prune(now)
        return this.utterances.map(({ speaker, text }) => `${speaker}: ${text}`).join('\n')
    }

    private prune(now: number): void {
        const cutoff = now - this.windowSeconds * 1000
        const firstKept = this.utterances.findIndex((utterance) => utterance.at >= cutoff)
        this.utterances = firstKept === -1 ? [] : this.utterances.slice(firstKept)
    }
}
