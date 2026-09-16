import type { ObservationSearchResultApi } from '../generated/api.schemas'
import { groupByTier } from './resultTiers'

const result = (distance: number): ObservationSearchResultApi =>
    ({ observation: { id: `d${distance}` }, distance, matched_content: '' }) as unknown as ObservationSearchResultApi

describe('groupByTier', () => {
    it.each([
        ['no cutoff keeps one untiered group', [0.1, 0.5], null, [[null, 2]]],
        [
            'splits at the cutoff',
            [0.1, 0.12, 0.4, 0.5],
            0.15,
            [
                ['top', 2],
                ['other', 2],
            ],
        ],
        ['all top', [0.1, 0.12], 0.15, [['top', 2]]],
        ['all other', [0.4, 0.5], 0.15, [['other', 2]]],
        ['empty', [], 0.15, []],
    ] as const)('%s', (_, distances, cutoff, expected) => {
        const groups = groupByTier(distances.map(result), cutoff)
        expect(groups.map((group) => [group.tier, group.results.length])).toEqual(expected)
    })
})
