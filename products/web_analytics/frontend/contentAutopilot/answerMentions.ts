export interface AnswerBrand {
    key: string
    name: string
    /** Bare domain, such as `example.com`. A link to it or a subdomain counts as citing the brand. */
    domain: string | null
    isOwn: boolean
    /** Words that name the brand in an answer: its name, aliases and domain. */
    terms: string[]
}

export interface AnswerSegment {
    text: string
    brandKey: string | null
}

export interface AnswerMention {
    brand: AnswerBrand
    count: number
    cited: boolean
}

export interface AnswerMentions {
    segments: AnswerSegment[]
    /** Brands the answer names, in the order it first names them. */
    mentions: AnswerMention[]
}

// Escapes only the characters that are syntax in a pattern. The pattern uses the `u` flag, which rejects any other
// escaped character, so a general escaper that also escapes `!`, `=` or `:` would throw on a name like "Yahoo!".
const escapeTerm = (term: string): string => term.replace(/[\\^$.*+?()[\]{}|/]/g, '\\$&')

const hostOf = (url: string): string | null => {
    try {
        return new URL(url).hostname.toLowerCase().replace(/^www\./, '')
    } catch {
        return null
    }
}

const citesDomain = (citedUrls: string[], domain: string): boolean => {
    const bare = domain.toLowerCase().replace(/^www\./, '')
    return citedUrls.some((url) => {
        const host = hostOf(url)
        return host !== null && (host === bare || host.endsWith(`.${bare}`))
    })
}

/** Splits an answer into plain text and brand names, and lists the brands it names. Matching is case-insensitive
 *  on whole words, and a longer term wins over a shorter one it contains ("PostHog Cloud" over "PostHog"). */
export function answerMentions(
    text: string,
    brands: AnswerBrand[],
    citedUrls: string[],
    ownCited: boolean
): AnswerMentions {
    const brandByTerm = new Map<string, AnswerBrand>()
    for (const brand of brands) {
        for (const term of brand.terms) {
            const key = term.trim().toLowerCase()
            // The first brand to claim a term keeps it, so the caller's order (own brand first) breaks ties.
            if (key.length > 1 && !brandByTerm.has(key)) {
                brandByTerm.set(key, brand)
            }
        }
    }
    if (!text || brandByTerm.size === 0) {
        return { segments: text ? [{ text, brandKey: null }] : [], mentions: [] }
    }
    const pattern = [...brandByTerm.keys()]
        .sort((a, b) => b.length - a.length)
        .map(escapeTerm)
        .join('|')
    // Lookarounds instead of \b, so a term that starts or ends with punctuation (a domain) still matches.
    const regex = new RegExp(`(?<![\\p{L}\\p{N}])(?:${pattern})(?![\\p{L}\\p{N}])`, 'giu')

    const segments: AnswerSegment[] = []
    const counts = new Map<string, number>()
    const order: AnswerBrand[] = []
    let last = 0
    for (const match of text.matchAll(regex)) {
        const brand = brandByTerm.get(match[0].toLowerCase())
        if (!brand) {
            continue
        }
        const start = match.index ?? 0
        if (start > last) {
            segments.push({ text: text.slice(last, start), brandKey: null })
        }
        segments.push({ text: match[0], brandKey: brand.key })
        last = start + match[0].length
        if (!counts.has(brand.key)) {
            order.push(brand)
        }
        counts.set(brand.key, (counts.get(brand.key) ?? 0) + 1)
    }
    if (last < text.length) {
        segments.push({ text: text.slice(last), brandKey: null })
    }

    return {
        segments,
        mentions: order.map((brand) => ({
            brand,
            count: counts.get(brand.key) ?? 0,
            cited: brand.isOwn ? ownCited : brand.domain !== null && citesDomain(citedUrls, brand.domain),
        })),
    }
}
