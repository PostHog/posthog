import { MakeLogicType, actions, afterMount, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { IntervalType } from '~/types'

import { visionScannersList } from '../generated/api'
import type { ReplayScanner } from './types'

export type SpendChartInterval = Extract<IntervalType, 'day' | 'week' | 'month'>

interface visionUsageLogicValues {
    usageScanners: ReplayScanner[]
    usageScannersError: boolean
    usageScannersLoading: boolean
    spendChartInterval: SpendChartInterval
}

interface visionUsageLogicActions {
    loadUsageScanners: () => void
    loadUsageScannersSuccess: (usageScanners: ReplayScanner[]) => { usageScanners: ReplayScanner[] }
    loadUsageScannersFailure: (error: string) => { error: string }
    setSpendChartInterval: (interval: SpendChartInterval) => { interval: SpendChartInterval }
}

export type visionUsageLogicType = MakeLogicType<visionUsageLogicValues, visionUsageLogicActions>

// Loads the whole team's scanners ordered by spend for the Usage tab and the overview's
// usage bridge. Separate from replayScannersLogic so the list tab's filters and
// pagination never leak into usage math.
export const visionUsageLogic = kea<visionUsageLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'visionUsageLogic']),
    actions({
        setSpendChartInterval: (interval: SpendChartInterval) => ({ interval }),
    }),
    reducers({
        spendChartInterval: [
            'day' as SpendChartInterval,
            {
                setSpendChartInterval: (_, { interval }) => interval,
            },
        ],
        // A failed read, so the tab shows a retry instead of "No spend this period yet", which reads
        // like the account is idle.
        usageScannersError: [
            false,
            {
                loadUsageScanners: () => false,
                loadUsageScannersSuccess: () => false,
                loadUsageScannersFailure: () => true,
            },
        ],
    }),
    loaders({
        usageScanners: [
            [] as ReplayScanner[],
            {
                loadUsageScanners: async (): Promise<ReplayScanner[]> => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return []
                    }
                    const response = await visionScannersList(String(teamId), {
                        order_by: '-credits_this_month',
                        limit: 100,
                    })
                    return (response.results ?? []) as unknown as ReplayScanner[]
                },
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadUsageScanners()
    }),
])
