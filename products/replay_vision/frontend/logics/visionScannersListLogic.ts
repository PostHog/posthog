import { afterMount, connect, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { visionScannersList } from '../generated/api'
import type { ReplayScannerApi } from '../generated/api.schemas'
import type { visionScannersListLogicType } from './visionScannersListLogicType'

const PAGE_LIMIT = 100

/** The team's full scanner list for pickers — shared and propless so each surface doesn't refetch its own copy. */
export const visionScannersListLogic = kea<visionScannersListLogicType>([
    path(['products', 'replay_vision', 'frontend', 'logics', 'visionScannersListLogic']),

    connect(() => ({
        actions: [teamLogic, ['loadCurrentTeamSuccess']],
    })),

    loaders({
        scanners: [
            [] as ReplayScannerApi[],
            {
                loadScanners: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return []
                    }
                    try {
                        // Follow pagination so pickers never silently truncate past the server page size.
                        const all: ReplayScannerApi[] = []
                        let offset = 0
                        for (;;) {
                            const response = await visionScannersList(String(teamId), {
                                limit: PAGE_LIMIT,
                                offset,
                            })
                            const results = response.results ?? []
                            all.push(...results)
                            if (!response.next || results.length === 0) {
                                return all
                            }
                            offset += PAGE_LIMIT
                        }
                    } catch {
                        return []
                    }
                },
            },
        ],
    }),

    listeners(({ actions }) => ({
        // Propless/global — reload on team switch so a stale list can't offer another team's scanner ids.
        loadCurrentTeamSuccess: () => actions.loadScanners(),
    })),

    afterMount(({ actions }) => {
        actions.loadScanners()
    }),
])
