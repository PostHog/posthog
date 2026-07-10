import { actions, kea, path, props, reducers, selectors } from 'kea'

import { DashboardTile, InsightModel } from '~/types'

import type { insightSelectorLogicType } from './insightSelectorLogicType'

// Keep in sync with DEFAULT_MAX_ASSET_COUNT in ee/tasks/subscriptions/subscription_utils.py
export const MAX_INSIGHTS = 6

export interface InsightSelectorLogicProps {
    tiles: DashboardTile[]
}

export const insightSelectorLogic = kea<insightSelectorLogicType>([
    props({} as InsightSelectorLogicProps),
    path(['lib', 'components', 'Subscriptions', 'insightSelectorLogic']),

    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setUserHasInteracted: true,
    }),

    reducers({
        searchTerm: ['', { setSearchTerm: (_, { searchTerm }) => searchTerm }],
        userHasInteracted: [false, { setUserHasInteracted: () => true }],
    }),

    selectors({
        insightTiles: [
            (_, p) => [p.tiles],
            (tiles): DashboardTile<InsightModel>[] =>
                ((tiles || []) as DashboardTile<InsightModel>[])
                    .filter(
                        (tile): tile is DashboardTile<InsightModel> =>
                            !!tile.insight && !tile.deleted && !tile.insight.deleted
                    )
                    .sort(
                        (a, b) =>
                            (a.layouts?.sm?.y ?? 100) - (b.layouts?.sm?.y ?? 100) ||
                            (a.layouts?.sm?.x ?? 100) - (b.layouts?.sm?.x ?? 100)
                    ),
        ],
        filteredTiles: [
            (s) => [s.insightTiles, s.searchTerm],
            (insightTiles, searchTerm): DashboardTile<InsightModel>[] => {
                if (!searchTerm.trim()) {
                    return insightTiles
                }
                const lowerSearch = searchTerm.toLowerCase()
                return insightTiles.filter((tile) => {
                    const name = tile.insight?.name || tile.insight?.derived_name || ''
                    return name.toLowerCase().includes(lowerSearch)
                })
            },
        ],
        showSearch: [(s) => [s.insightTiles], (insightTiles) => insightTiles.length > 10],
    }),
])
