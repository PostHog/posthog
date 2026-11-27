import type {
    AEOKeywordModifierApi,
    AEOKeywordReportRowApi,
    ModifierKindEnumApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

// Matches the backend cap, so the form can say how many keywords are left before a request fails.
export const MAX_KEYWORDS = 200
// A share over fewer answers than this moves by 20 points or more with each new answer, so the report
// table shows the count of answers instead of the share.
export const MIN_RATED_ANSWERS = 5
// A modifier whose answers cite the site this many points less often than all answers is a content gap.
export const CITATION_GAP_POINTS = 0.1
// Rates are floats, so 0.5 - 0.4 comes out a hair under 0.1 and would miss the threshold it sits on.
const RATE_EPSILON = 1e-9

/** Splits pasted text on commas and new lines into keywords, normalized the way the API stores them. */
export const keywordLines = (text: string): string[] => {
    const keywords = text
        .split(/[,\n]/)
        .map((line) => line.split(/\s+/).filter(Boolean).join(' ').toLowerCase())
        .filter(Boolean)
    return [...new Set(keywords)]
}

export const keywordsAddedMessage = ({ created, skipped }: { created: number; skipped: number }): string => {
    const added = created === 1 ? 'Added 1 keyword.' : `Added ${created} keywords.`
    if (!skipped) {
        return added
    }
    return `${added} Skipped ${skipped} that ${skipped === 1 ? 'was' : 'were'} empty or already in the list.`
}

export interface ModifierGroup {
    kind: ModifierKindEnumApi
    label: string
    description: string
    answers: number
    modifiers: AEOKeywordModifierApi[]
}

const MODIFIER_GROUPS: Record<ModifierKindEnumApi, Pick<ModifierGroup, 'label' | 'description'>> = {
    comparison: { label: 'Comparisons', description: 'Words like "vs", "alternatives" and "best".' },
    pricing: { label: 'Pricing', description: 'Words like "pricing", "cost" and "free".' },
    freshness: { label: 'Freshness', description: 'A year, or words like "latest" and "new".' },
    docs: { label: 'Docs and guides', description: 'Words like "docs", "official", "api" and "tutorial".' },
    competitor: { label: 'Competitors', description: 'Competitors from your brand catalog.' },
    site: { label: 'Site searches', description: 'Searches limited to one site with "site:".' },
    other: { label: 'Other words', description: 'Words that fit no other group.' },
}

/** Groups modifiers by kind, in a fixed order, leaving out kinds with no modifier. */
export const modifierGroups = (modifiers: AEOKeywordModifierApi[]): ModifierGroup[] =>
    (Object.keys(MODIFIER_GROUPS) as ModifierKindEnumApi[])
        .map((kind) => {
            const ofKind = modifiers.filter((modifier) => modifier.kind === kind)
            return {
                kind,
                ...MODIFIER_GROUPS[kind],
                answers: Math.max(0, ...ofKind.map((modifier) => modifier.answers)),
                modifiers: ofKind,
            }
        })
        .filter((group) => group.modifiers.length > 0)

export const isCitationGap = (
    modifier: Pick<AEOKeywordModifierApi, 'cited_rate'>,
    baselineCitedRate: number | null
): boolean =>
    modifier.cited_rate !== null &&
    baselineCitedRate !== null &&
    baselineCitedRate - modifier.cited_rate >= CITATION_GAP_POINTS - RATE_EPSILON

export interface SampledRate {
    rate: number | null
    sample: number
}

export type ReportRateKey = 'visibility' | 'searched' | 'searched_cited' | 'prompt_mention' | 'prompt_cited'

export const reportRate = (row: AEOKeywordReportRowApi, key: ReportRateKey, totalAnswers: number): SampledRate => {
    switch (key) {
        case 'visibility':
            return { rate: row.answer_mention_rate, sample: row.answer_checks }
        case 'searched':
            return { rate: row.searched_rate, sample: totalAnswers }
        case 'searched_cited':
            return { rate: row.searched_cited_rate, sample: row.searched_checks }
        case 'prompt_mention':
            return { rate: row.prompt_mention_rate, sample: row.prompt_checks }
        case 'prompt_cited':
            return { rate: row.prompt_cited_rate, sample: row.prompt_checks }
    }
}

export const isRated = (sampled: SampledRate): sampled is SampledRate & { rate: number } =>
    sampled.rate !== null && sampled.sample >= MIN_RATED_ANSWERS

/**
 * Orders rated shares by value and keeps the unrated ones (no answers, or fewer than MIN_RATED_ANSWERS)
 * after them. LemonTable multiplies the result by `order`, so the unrated half is pre-multiplied to stay
 * last whichever way the column sorts. Among unrated rows, more answers come first.
 */
export const compareSampledRates =
    (order: 1 | -1) =>
    (a: SampledRate, b: SampledRate): number => {
        const ratedA = isRated(a)
        const ratedB = isRated(b)
        if (ratedA && ratedB) {
            return a.rate - b.rate
        }
        if (ratedA !== ratedB) {
            return order * (ratedA ? -1 : 1)
        }
        return order * (b.sample - a.sample)
    }
