import { MakeLogicType, actions, afterMount, connect, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { IntervalType } from '~/types'

import { visionScannersList } from '../generated/api'
import type { ReplayScanner } from './types'

export type SpendChartInterval = Extract<IntervalType, 'day' | 'week' | 'month'>

interface visionUsageLogicValues {
    usageScanners: ReplayScanner[]
    usageScannersLoading: boolean
    spendChartInterval: SpendChartInterval
    isCurrentTeamUnavailable: boolean
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
    connect(() => ({
        values: [teamLogic, ['isCurrentTeamUnavailable']],
    })),
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
    afterMount(({ actions, values }) => {
        // Don't fire the request when the user has no access to the current project -
        // it would just 403 and the page's own access-denied gate already covers this case.
        if (!values.isCurrentTeamUnavailable) {
            actions.loadUsageScanners()
        }
    }),
])
