import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { DashboardTile } from '~/types'

import { insightSelectorLogic } from './insightSelectorLogic'

const createMockTiles = (): Partial<DashboardTile>[] => [
    { id: 1, insight: { id: 101, name: 'Pageviews' } as any, layouts: { sm: { x: 0, y: 0 } } },
    { id: 2, insight: { id: 102, name: 'Sessions' } as any, layouts: { sm: { x: 0, y: 1 } } },
    { id: 3, insight: { id: 103, name: 'Users' } as any, layouts: { sm: { x: 0, y: 2 } } },
    { id: 4, insight: null } as any, // Text tile - should be filtered out
    { id: 5, insight: { id: 105, name: 'Revenue' } as any, deleted: true }, // Deleted tile - filtered out
    { id: 6, insight: { id: 106, name: 'Churned', deleted: true } as any }, // Deleted insight - filtered out
]

describe('insightSelectorLogic', () => {
    let logic: ReturnType<typeof insightSelectorLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('filters out non-insight and deleted tiles', () => {
        logic = insightSelectorLogic({ tiles: createMockTiles() as DashboardTile[] })
        logic.mount()

        expectLogic(logic).toMatchValues({
            insightTiles: [
                expect.objectContaining({ id: 1 }),
                expect.objectContaining({ id: 2 }),
                expect.objectContaining({ id: 3 }),
            ],
        })
    })

    it('sorts tiles by layout position (y first, then x)', () => {
        const unsortedTiles = [
            { id: 1, insight: { id: 101, name: 'A' } as any, layouts: { sm: { x: 1, y: 1 } } },
            { id: 2, insight: { id: 102, name: 'B' } as any, layouts: { sm: { x: 0, y: 0 } } },
            { id: 3, insight: { id: 103, name: 'C' } as any, layouts: { sm: { x: 1, y: 0 } } },
        ]
        logic = insightSelectorLogic({ tiles: unsortedTiles as DashboardTile[] })
        logic.mount()

        expectLogic(logic).toMatchValues({
            insightTiles: [
                expect.objectContaining({ id: 2 }), // y=0, x=0
                expect.objectContaining({ id: 3 }), // y=0, x=1
                expect.objectContaining({ id: 1 }), // y=1, x=1
            ],
        })
    })

    it('filters tiles by search term (case insensitive)', () => {
        logic = insightSelectorLogic({ tiles: createMockTiles() as DashboardTile[] })
        logic.mount()

        expectLogic(logic, () => logic.actions.setSearchTerm('PAGE')).toMatchValues({
            filteredTiles: [expect.objectContaining({ id: 1 })],
        })
    })

    it('returns all tiles when search term is empty', () => {
        logic = insightSelectorLogic({ tiles: createMockTiles() as DashboardTile[] })
        logic.mount()

        expectLogic(logic, () => logic.actions.setSearchTerm('')).toMatchValues({
            filteredTiles: [
                expect.objectContaining({ id: 1 }),
                expect.objectContaining({ id: 2 }),
                expect.objectContaining({ id: 3 }),
            ],
        })
    })

    it('returns empty array when no tiles match search', () => {
        logic = insightSelectorLogic({ tiles: createMockTiles() as DashboardTile[] })
        logic.mount()

        expectLogic(logic, () => logic.actions.setSearchTerm('nonexistent')).toMatchValues({
            filteredTiles: [],
        })
    })

    it('shows search only when more than 10 tiles', () => {
        logic = insightSelectorLogic({ tiles: createMockTiles() as DashboardTile[] })
        logic.mount()

        expectLogic(logic).toMatchValues({ showSearch: false })
    })

    it('shows search when more than 10 insight tiles', () => {
        const manyTiles = Array.from({ length: 11 }, (_, i) => ({
            id: i,
            insight: { id: i, name: `Insight ${i}` } as any,
            layouts: { sm: { x: 0, y: i } },
        }))
        logic = insightSelectorLogic({ tiles: manyTiles as DashboardTile[] })
        logic.mount()

        expectLogic(logic).toMatchValues({ showSearch: true })
    })

    it('handles empty tiles array', () => {
        logic = insightSelectorLogic({ tiles: [] })
        logic.mount()

        expectLogic(logic).toMatchValues({
            insightTiles: [],
            filteredTiles: [],
            showSearch: false,
        })
    })

    it('handles tiles with missing layouts gracefully', () => {
        const tilesWithoutLayouts = [
            { id: 1, insight: { id: 101, name: 'A' } as any },
            { id: 2, insight: { id: 102, name: 'B' } as any, layouts: {} },
            { id: 3, insight: { id: 103, name: 'C' } as any, layouts: { sm: { x: 0, y: 0 } } },
        ]
        logic = insightSelectorLogic({ tiles: tilesWithoutLayouts as DashboardTile[] })
        logic.mount()

        // Should not throw and should include all insight tiles
        expectLogic(logic).toMatchValues({
            insightTiles: expect.arrayContaining([
                expect.objectContaining({ id: 1 }),
                expect.objectContaining({ id: 2 }),
                expect.objectContaining({ id: 3 }),
            ]),
        })
    })
})
