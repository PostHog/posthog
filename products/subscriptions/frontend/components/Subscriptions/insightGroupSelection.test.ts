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
            { ...tile(9, 12, 'a'), deleted: true },
            { ...tile(10, 13, 'a'), insight: { id: 110, name: 'Deleted insight', deleted: true } } as DashboardTile,
            tile(4, 15, 'b'),
            tile(5, 20, 'text-only', null),
            tile(6, 25, null),
            tile(7, 30, 'untitled'),
            tile(8, 35, 'untitled', null),
            tile(11, 120, 'a'),
            // No saved layout sorts as y=100, the same as the flat list and the sent report.
            { ...tile(12, 0, 'a'), layouts: {} } as DashboardTile,
        ]

        const result = getInsightGroups({
            tiles,
            groups: { a: { title: 'Acquisition' }, b: { title: 'Billing' } },
            groupDisplay,
        })

        expect(result.map(({ label, insightIds }) => ({ label, insightIds }))).toEqual([
            { label: ungroupedLabel, insightIds: [101, 106] },
            { label: 'Billing', insightIds: [102, 104] },
            { label: 'Acquisition', insightIds: [103, 112, 111] },
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
        // A fully selected group stays clickable even when an older selection is already over the limit.
        ['all selected while over the limit', [1, 2, 3, 9], true, null],
        // Clicking clears it instead, so it stays enabled.
        ['part selected and the rest would go over the limit', [1, 9], 'indeterminate', null],
        [
            'nothing selected and the group would go over the limit',
            [8, 9],
            false,
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
        ['adds the missing insights of a partly selected group', [999, 1, 5], [1, 5], 10, [999, 1, 5, 2, 3]],
        ['removes a fully selected group', [999, 1, 2, 3, 5], [1, 2, 3, 5], 10, [999, 5]],
        [
            'clears a partly selected group whose rest would go over the limit',
            [999, 1, 5, 6],
            [1, 5, 6],
            3,
            [999, 5, 6],
        ],
    ])('%s', (_name, selectedInsightIds, validSelectedIds, maxInsights, expected) => {
        expect(
            toggleInsightGroup({ group: group([1, 2, 3]), selectedInsightIds, validSelectedIds, maxInsights })
        ).toEqual(expected)
    })
})
