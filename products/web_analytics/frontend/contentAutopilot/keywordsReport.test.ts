import type { AEOKeywordModifierApi } from '../generated/api.schemas'
import { isCitationGap, keywordLines, keywordsAddedMessage, modifierGroups } from './keywordsReport'

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
})
