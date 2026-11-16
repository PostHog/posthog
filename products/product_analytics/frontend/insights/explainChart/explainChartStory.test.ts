import type { insightLogicValues } from 'scenes/insights/insightLogic'

import { explainChartStoryFor } from './explainChartStory'

const INSIGHT = { id: 42, short_id: 'aBc12345' } as insightLogicValues['insight']
const STORY = {
    query: { kind: 'TrendsQuery' },
    results: [{ label: 'Pageviews', data: [1, 2, 3], days: ['2026-10-01', '2026-10-02', '2026-10-03'] }],
    seriesIndex: 0,
    insightName: 'Pageviews',
    lastPointInProgress: false,
    headline: 'A peak on **October 2**.',
    chapters: [],
}

describe('explainChartStoryFor', () => {
    test.each([
        ['the short id', { insightId: 'aBc12345' }, STORY, STORY],
        ['the numeric id under an alias', { id: 42 }, STORY, STORY],
        ['another insight', { insightId: 'zzz99999' }, STORY, null],
        ['an unsaved query', { query: { kind: 'TrendsQuery' } }, STORY, null],
        ['a result that is not a story', { insightId: 'aBc12345' }, { headline: 'A peak' }, null],
    ])('takes a story for %s only when it explains this insight', (_, input, output, expected) => {
        expect(explainChartStoryFor(INSIGHT, input, output)).toEqual(expected)
    })
})
