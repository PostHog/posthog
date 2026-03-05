import { actions, kea, path, reducers, selectors } from 'kea'

import type { recommendationsLogicType } from './recommendationsLogicType'

export type TileDismissalState = {
    permanent: boolean
    expiresAt?: number
}

export const recommendationsLogic = kea<recommendationsLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingScene',
        'tabs',
        'recommendations',
        'recommendationsLogic',
    ]),

    actions({
        dismissTile: (tileId: string) => ({ tileId }),
        snoozeTile: (tileId: string, days: number) => ({ tileId, days }),
        restoreTile: (tileId: string) => ({ tileId }),
        suppressIssue: (issueId: string) => ({ issueId }),
    }),

    reducers({
        dismissedTiles: [
            {} as Record<string, TileDismissalState>,
            { persist: true },
            {
                dismissTile: (state, { tileId }) => ({
                    ...state,
                    [tileId]: { permanent: true },
                }),
                snoozeTile: (state, { tileId, days }) => ({
                    ...state,
                    [tileId]: {
                        permanent: false,
                        expiresAt: Date.now() + days * 24 * 60 * 60 * 1000,
                    },
                }),
                restoreTile: (state, { tileId }) => {
                    const next = { ...state }
                    delete next[tileId]
                    return next
                },
            },
        ],
        suppressedIssueIds: [
            [] as string[],
            { persist: true },
            {
                suppressIssue: (state, { issueId }) => [...state, issueId],
            },
        ],
    }),

    selectors({
        visibleTileIds: [
            (s) => [s.dismissedTiles],
            (dismissedTiles): ((tileId: string) => boolean) => {
                return (tileId: string): boolean => {
                    const entry = dismissedTiles[tileId]
                    if (!entry) {
                        return true
                    }
                    if (entry.permanent) {
                        return false
                    }
                    if (entry.expiresAt && Date.now() >= entry.expiresAt) {
                        return true
                    }
                    return false
                }
            },
        ],
    }),
])
