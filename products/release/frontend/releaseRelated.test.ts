import { RankInput, RelatedInsight, RelatedSurvey, flagKeysPattern, rankRelatedSuggestions } from './releaseRelated'

const survey = (id: string, name: string, extra: Partial<RelatedSurvey> = {}): RelatedSurvey => ({
    id,
    name,
    createdAt: '2026-11-01T00:00:00Z',
    startDate: null,
    endDate: null,
    linkedFlagId: null,
    archived: false,
    ...extra,
})

const insight = (id: number, name: string): RelatedInsight => ({
    id,
    shortId: `short-${id}`,
    name,
    createdAt: '2026-11-01T00:00:00Z',
    lastModifiedAt: null,
})

const input = (extra: Partial<RankInput>): RankInput => ({
    tokens: ['quiet', 'theme'],
    flags: [{ id: 7, key: 'quiet-theme' }],
    linkedSurveyIds: new Set(),
    linkedInsightIds: new Set(),
    flagSurveys: [],
    flagInsights: [],
    nameSurveys: [],
    nameInsights: [],
    ...extra,
})

describe('releaseRelated', () => {
    it.each([
        ['"$feature/quiet-theme"', true],
        ['$feature/quiet-theme', true],
        ['{"key":"$feature/quiet-theme","value":true}', true],
        ['$feature/quiet-theme-paid', false],
        ['$feature/quiet-theme_v2', false],
        ['$feature/quiet', false],
    ])('matches %s against quiet-theme: %s', (text, matches) => {
        expect(new RegExp(flagKeysPattern(['quiet-theme'])).test(text)).toBe(matches)
    })

    it('escapes regex characters in flag keys', () => {
        expect(new RegExp(flagKeysPattern(['a.b'])).test('$feature/aXb')).toBe(false)
    })

    it('puts flag-linked items first, skips linked and archived ones, and ranks name matches by shared words', () => {
        const ranked = rankRelatedSuggestions(
            input({
                linkedSurveyIds: new Set(['linked']),
                flagSurveys: [
                    survey('flagged', 'Exit poll', { linkedFlagId: 7 }),
                    survey('linked', 'Already in'),
                    survey('old', 'Archived', { archived: true }),
                ],
                flagInsights: [insight(1, 'Adoption')],
                nameSurveys: [
                    survey('theme', 'Theme check'),
                    survey('flagged', 'Quiet theme exit poll'),
                    survey('linked', 'Quiet theme notes'),
                    survey('retired', 'Quiet theme pulse', { archived: true }),
                ],
                nameInsights: [insight(2, 'Quiet theme retention'), insight(3, 'Unrelated')],
            })
        )

        expect(ranked.map(({ key, reason }) => [key, reason])).toEqual([
            ['survey:flagged', 'Shown to people who get quiet-theme'],
            ['insight:1', 'Breaks down or filters by a flag in this release'],
            ['insight:2', 'Name matches this release'],
            ['survey:theme', 'Name matches this release'],
        ])
    })
})
