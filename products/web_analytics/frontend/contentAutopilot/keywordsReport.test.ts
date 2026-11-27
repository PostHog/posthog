import type { AEOKeywordModifierApi, AEOKeywordReportRowApi } from '../generated/api.schemas'
import {
    MIN_RATED_ANSWERS,
    type SampledRate,
    compareSampledRates,
    isCitationGap,
    isRated,
    keywordLines,
    keywordsAddedMessage,
    modifierGroups,
    reportRate,
} from './keywordsReport'

const modifier = (term: string, kind: AEOKeywordModifierApi['kind'], answers: number): AEOKeywordModifierApi => ({
    term,
    kind,
    answers,
    share: answers / 10,
    cited_rate: 0.5,
    engines: [],
    example_searches: [],
})

describe('keywordsReport', () => {
    it.each([
        ['one keyword', 'Pricing', ['pricing']],
        [
            'commas and new lines',
            'pricing, session replay\nfeature flags,\n\n',
            ['pricing', 'session replay', 'feature flags'],
        ],
        ['whitespace and case', '  Session    Replay \n session replay', ['session replay']],
        ['only separators', ' , \n ,', []],
    ])('parses pasted keywords: %s', (_name, text, expected) => {
        expect(keywordLines(text)).toEqual(expected)
    })

    it.each([
        [{ created: 1, skipped: 0 }, 'Added 1 keyword.'],
        [{ created: 3, skipped: 2 }, 'Added 3 keywords. Skipped 2 that were empty or already in the list.'],
    ])('describes the add result %o', (result, expected) => {
        expect(keywordsAddedMessage(result)).toEqual(expected)
    })

    it('groups modifiers by kind in a fixed order and drops empty kinds', () => {
        const groups = modifierGroups([
            modifier('2026', 'freshness', 4),
            modifier('vs acme', 'comparison', 2),
            modifier('latest', 'freshness', 6),
        ])

        expect(groups.map((group) => [group.kind, group.answers, group.modifiers.map((m) => m.term)])).toEqual([
            ['comparison', 2, ['vs acme']],
            ['freshness', 6, ['2026', 'latest']],
        ])
    })

    it.each([
        [0.2, 0.5, true],
        [0.4, 0.5, true],
        [0.45, 0.5, false],
        [null, 0.5, false],
        [0.2, null, false],
    ])('flags cited rate %p against baseline %p as a gap: %p', (citedRate, baseline, expected) => {
        expect(isCitationGap({ cited_rate: citedRate }, baseline)).toBe(expected)
    })

    it.each([
        ['a share over enough answers', { rate: 0.5, sample: MIN_RATED_ANSWERS }, true],
        ['one answer short', { rate: 1, sample: MIN_RATED_ANSWERS - 1 }, false],
        ['no answers', { rate: null, sample: 0 }, false],
    ])('rates %s: %p', (_name, sampled: SampledRate, expected) => {
        expect(isRated(sampled)).toBe(expected)
    })

    const sortedKeys = (rates: Record<string, SampledRate>, order: 1 | -1): string[] =>
        Object.keys(rates).sort((a, b) => order * compareSampledRates(order)(rates[a], rates[b]))

    it.each<[1 | -1, string[]]>([
        [-1, ['high', 'low', 'few-more', 'few', 'none']],
        [1, ['low', 'high', 'few-more', 'few', 'none']],
    ])('sorts rows without enough answers below rated rows with order %p', (order, expected) => {
        const rates: Record<string, SampledRate> = {
            few: { rate: 1, sample: 1 },
            low: { rate: 0.1, sample: 40 },
            none: { rate: null, sample: 0 },
            high: { rate: 0.9, sample: 12 },
            'few-more': { rate: 0, sample: 3 },
        }
        expect(sortedKeys(rates, order)).toEqual(expected)
    })

    it('measures the searched share over every answer in the window', () => {
        const row = { searched_rate: 0.2, searched_checks: 3, answer_checks: 9 } as AEOKeywordReportRowApi
        expect(reportRate(row, 'searched', 15)).toEqual({ rate: 0.2, sample: 15 })
        expect(reportRate(row, 'searched_cited', 15).sample).toBe(3)
    })
})
