import { DashboardTile } from '~/types'

import {
    InsightGroup,
    getInsightGroupCheckboxState,
    getInsightGroups,
    toggleInsightGroup,
} from './insightGroupSelection'

const tile = (id: number, y: number, groupKey: string | null, insightId: number | null = id + 100): DashboardTile =>
    ({
        id,
        insight: insightId === null ? undefined : { id: insightId, name: `Insight ${insightId}` },
        layouts: { sm: { x: 0, y, w: 6, h: 5 } },
        group_key: groupKey,
    }) as unknown as DashboardTile

const group = (insightIds: number[]): InsightGroup => ({ key: 'g', label: 'G', tiles: [], insightIds })

describe('insightGroupSelection', () => {
    it.each([
        ['tabs', 'Overview'],
        ['sections', 'Not in a group'],
    ] as const)('splits insights into the dashboard groups with %s display', (groupDisplay, ungroupedLabel) => {
        const tiles = [
            tile(1, 0, null),
            tile(2, 5, 'b'),
            tile(3, 10, 'a'),
            tile(4, 15, 'b'),
            tile(5, 20, 'text-only', null),
            tile(6, 25, null),
            tile(7, 30, 'untitled'),
            tile(8, 35, 'untitled', null),
        ]

        const result = getInsightGroups({
            tiles,
            groups: { a: { title: 'Acquisition' }, b: { title: 'Billing' } },
            groupDisplay,
        })

        expect(result.map(({ label, insightIds }) => ({ label, insightIds }))).toEqual([
            { label: ungroupedLabel, insightIds: [101, 106] },
            { label: 'Billing', insightIds: [102, 104] },
            { label: 'Acquisition', insightIds: [103] },
            // An untitled group is named by its tile count, as on the dashboard.
            { label: '2\u00a0tiles', insightIds: [107] },
        ])
    })

    it('returns no groups when no insight is in a group', () => {
        expect(
            getInsightGroups({
                tiles: [tile(1, 0, null), tile(2, 5, 'text-only', null)],
                groups: undefined,
                groupDisplay: 'tabs',
            })
        ).toEqual([])
    })

    it.each([
        ['nothing selected', [], false, null],
        ['part selected', [1], 'indeterminate', null],
        ['all selected at the limit', [1, 2, 3], true, null],
        [
            'adding would go over the limit',
            [1, 9],
            'indeterminate',
            'Selecting this tab would go over the limit of 3 insights. Deselect some insights first.',
        ],
    ] as const)('checkbox state with %s', (_name, validSelectedIds, checked, disabledReason) => {
        expect(
            getInsightGroupCheckboxState({
                group: group([1, 2, 3]),
                validSelectedIds: [...validSelectedIds],
                maxInsights: 3,
                groupDisplay: 'tabs',
            })
        ).toEqual({ checked, disabledReason })
    })

    it.each([
        ['adds the missing insights of a partly selected group', [999, 1, 5], [1, 5], [999, 1, 5, 2, 3]],
        ['removes a fully selected group', [999, 1, 2, 3, 5], [1, 2, 3, 5], [999, 5]],
    ])('%s', (_name, selectedInsightIds, validSelectedIds, expected) => {
        expect(toggleInsightGroup({ group: group([1, 2, 3]), selectedInsightIds, validSelectedIds })).toEqual(expected)
    })
})
