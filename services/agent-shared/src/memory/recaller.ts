// Recall ranking — the swap point.
//
// `prime` (prime.ts) depends only on this interface, never on how ranking
// works. v0 ships an in-memory full-text ranker (no external deps, no model,
// no pgvector). A future embedding-backed ranker (precompute vectors on write,
// cosine KNN) implements the same interface and drops in with ZERO change to
// the tool surface or prime. See docs/agent-platform/plans/agent-memory-mnemion-slice.md §5.

export interface Candidate {
    pattern: string
    id: number
    /** Text built from the entry's string facets — what we rank against. */
    text: string
    entry: Record<string, unknown>
}

export interface Ranked {
    pattern: string
    id: number
    /** 0..1; comparable only within one ranker. */
    score: number
    entry: Record<string, unknown>
}

export interface Recaller {
    /** Stable id for logging/observability — e.g. "fts-v0", "embedding-bge". */
    readonly kind: string
    rank(cue: string, candidates: Candidate[], limit: number): Promise<Ranked[]>
}

// === v0: in-memory full-text ranker ===

const STOPWORDS = new Set([
    'the',
    'a',
    'an',
    'and',
    'or',
    'but',
    'of',
    'to',
    'in',
    'on',
    'at',
    'for',
    'is',
    'are',
    'was',
    'were',
    'be',
    'been',
    'it',
    'this',
    'that',
    'with',
    'as',
    'by',
    'from',
    'i',
    'you',
    'we',
    'they',
    'do',
    'does',
    'how',
    'what',
])

function tokenize(text: string): string[] {
    return text
        .toLowerCase()
        .split(/[^a-z0-9]+/)
        .filter((t) => t.length > 2 && !STOPWORDS.has(t))
}

function termFreq(tokens: string[]): Map<string, number> {
    const tf = new Map<string, number>()
    for (const t of tokens) {
        tf.set(t, (tf.get(t) ?? 0) + 1)
    }
    return tf
}

/**
 * Cosine similarity over bag-of-words term frequencies, with an idf weight so
 * rare shared terms count more than common ones. Good enough to demonstrate
 * "describe the moment, get back what's near it" without embeddings.
 */
export class FullTextRecaller implements Recaller {
    readonly kind = 'fts-v0'

    async rank(cue: string, candidates: Candidate[], limit: number): Promise<Ranked[]> {
        const cueTf = termFreq(tokenize(cue))
        if (cueTf.size === 0 || candidates.length === 0) {
            return []
        }

        // Document frequency across the candidate set → idf.
        const df = new Map<string, number>()
        const candTfs = candidates.map((c) => {
            const tf = termFreq(tokenize(c.text))
            for (const term of tf.keys()) {
                df.set(term, (df.get(term) ?? 0) + 1)
            }
            return tf
        })
        const N = candidates.length
        const idf = (term: string): number => Math.log((N + 1) / ((df.get(term) ?? 0) + 1)) + 1

        const cueNorm = vecNorm(cueTf, idf)
        const scored: Ranked[] = candidates.map((c, i) => {
            const tf = candTfs[i]
            let dot = 0
            for (const [term, q] of cueTf) {
                const d = tf.get(term)
                if (d) {
                    dot += q * d * idf(term) * idf(term)
                }
            }
            const denom = cueNorm * vecNorm(tf, idf)
            return {
                pattern: c.pattern,
                id: c.id,
                score: denom === 0 ? 0 : Math.round((dot / denom) * 1000) / 1000,
                entry: c.entry,
            }
        })

        return scored
            .filter((r) => r.score > 0)
            .sort((a, b) => b.score - a.score)
            .slice(0, limit)
    }
}

function vecNorm(tf: Map<string, number>, idf: (t: string) => number): number {
    let sum = 0
    for (const [term, f] of tf) {
        const w = f * idf(term)
        sum += w * w
    }
    return Math.sqrt(sum)
}
