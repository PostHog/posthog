import { actions, afterMount, connect, isBreakpoint, kea, listeners, path } from 'kea'
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

    actions({
        // Declared here so the action stays zero-arg despite the loader's `breakpoint` parameter.
        loadScanners: true,
    }),

    loaders(({ values }) => ({
        scanners: [
            [] as ReplayScannerApi[],
            {
                loadScanners: async (_, breakpoint) => {
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
                            // Cancel superseded loops (e.g. team switch) so a stale multi-page fetch can't win.
                            breakpoint()
                            const results = response.results ?? []
                            all.push(...results)
                            if (!response.next || results.length === 0) {
                                return all
                            }
                            offset += results.length
                        }
                    } catch (error) {
                        if (error instanceof Error && isBreakpoint(error)) {
                            throw error
                        }
                        return values.scanners
                    }
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        // Propless/global — reload on team switch so a stale list can't offer another team's scanner ids.
        loadCurrentTeamSuccess: () => actions.loadScanners(),
    })),

    afterMount(({ actions }) => {
        actions.loadScanners()
    }),
])
