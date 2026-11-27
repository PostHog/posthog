import type {
    AEOPromptSetOverviewApi,
    AEOPromptSetRankingsApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { firstResultsView } from './firstResults'

const brand = (domain: string, mentioning: number, isTarget = false): AEOPromptSetRankingsApi['brands'][number] => ({
    domain,
    name: domain.split('.')[0],
    is_target: isTarget,
    answers_mentioning: mentioning,
    visibility: 0.99,
    previous_visibility: null,
    positive_share: null,
})

const overviewOf = (checks: number, failed: number, mentioned: number, cited: number): AEOPromptSetOverviewApi =>
    ({ current: { checks, failed, mentioned, cited, prompts: 0, prompts_cited: 0 } }) as AEOPromptSetOverviewApi

describe('firstResults', () => {
    const nonBranded = overviewOf(10, 2, 2, 1)
    const branded = overviewOf(2, 0, 2, 1)
    const rankings = {
        answers: 10,
        brands: [brand('a.com', 7), brand('b.com', 5), brand('zero.com', 0), brand('you.com', 0, true)],
    } as AEOPromptSetRankingsApi

    it('works out every share on the step from the answers the subtitle states', () => {
        const view = firstResultsView(nonBranded, branded, rankings)

        expect(view.openAnswers).toBe(8)
        expect(view.brandedAnswers).toBe(2)
        expect(view.brands.map(({ domain, visibility }) => [domain, visibility])).toEqual([
            ['a.com', 7 / 8],
            ['b.com', 5 / 8],
            ['you.com', 0],
        ])
    })

    it.each([
        ['leaves out brands no answer named', 6, ['a.com', 'b.com', 'you.com']],
        ['keeps your own brand when it ranks below the cut', 2, ['a.com', 'you.com']],
    ])('%s', (_name, limit, expected) => {
        expect(firstResultsView(nonBranded, branded, rankings, limit).brands.map(({ domain }) => domain)).toEqual(
            expected
        )
    })
})
