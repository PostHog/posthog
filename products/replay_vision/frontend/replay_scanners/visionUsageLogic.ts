import { MakeLogicType, actions, afterMount, kea, listeners, path, reducers } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { IntervalType } from '~/types'

import { visionScannersList, visionScannersPartialUpdate } from '../generated/api'
import { refreshVisionQuota } from '../logics/visionQuotaLogic'
import type { ReplayScanner } from './types'

export type SpendChartInterval = Extract<IntervalType, 'day' | 'week' | 'month'>

interface visionUsageLogicValues {
    usageScanners: ReplayScanner[]
    usageScannersLoading: boolean
    spendChartInterval: SpendChartInterval
    togglingScannerIds: string[]
}

interface visionUsageLogicActions {
    loadUsageScanners: () => { value: true }
    loadUsageScannersSuccess: (usageScanners: ReplayScanner[]) => { usageScanners: ReplayScanner[] }
    setSpendChartInterval: (interval: SpendChartInterval) => { interval: SpendChartInterval }
    toggleScannerEnabled: (scanner: ReplayScanner) => { scanner: ReplayScanner }
    setScannerEnabled: (id: string, enabled: boolean) => { id: string; enabled: boolean }
    finishTogglingScanner: (id: string) => { id: string }
}

export type visionUsageLogicType = MakeLogicType<visionUsageLogicValues, visionUsageLogicActions>

// Loads the whole team's scanners ordered by spend for the Usage tab and the overview's
// usage bridge. Separate from replayScannersLogic so the list tab's filters and
// pagination never leak into usage math. Loaded manually rather than via kea-loaders so a
// per-row enable toggle can update the list optimistically without a refetch.
export const visionUsageLogic = kea<visionUsageLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'visionUsageLogic']),
    actions({
        loadUsageScanners: true,
        loadUsageScannersSuccess: (usageScanners: ReplayScanner[]) => ({ usageScanners }),
        setSpendChartInterval: (interval: SpendChartInterval) => ({ interval }),
        toggleScannerEnabled: (scanner: ReplayScanner) => ({ scanner }),
        setScannerEnabled: (id: string, enabled: boolean) => ({ id, enabled }),
        finishTogglingScanner: (id: string) => ({ id }),
    }),
    reducers({
        usageScanners: [
            [] as ReplayScanner[],
            {
                loadUsageScannersSuccess: (_, { usageScanners }) => usageScanners,
                setScannerEnabled: (state, { id, enabled }) =>
                    state.map((scanner) => (scanner.id === id ? { ...scanner, enabled } : scanner)),
            },
        ],
        usageScannersLoading: [
            false,
            {
                loadUsageScanners: () => true,
                loadUsageScannersSuccess: () => false,
            },
        ],
        spendChartInterval: [
            'day' as SpendChartInterval,
            {
                setSpendChartInterval: (_, { interval }) => interval,
            },
        ],
        togglingScannerIds: [
            [] as string[],
            {
                toggleScannerEnabled: (state, { scanner }) =>
                    state.includes(scanner.id) ? state : [...state, scanner.id],
                finishTogglingScanner: (state, { id }) => state.filter((toggling) => toggling !== id),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadUsageScanners: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.loadUsageScannersSuccess([])
                return
            }
            try {
                const response = await visionScannersList(String(teamId), {
                    order_by: '-credits_this_month',
                    limit: 100,
                })
                actions.loadUsageScannersSuccess((response.results ?? []) as unknown as ReplayScanner[])
            } catch {
                // Keep whatever list is already shown; the table's own empty/loaded state stays consistent.
                actions.loadUsageScannersSuccess(values.usageScanners)
            }
        },
        toggleScannerEnabled: async ({ scanner }) => {
            const teamId = teamLogic.values.currentTeamId
            const next = !scanner.enabled
            if (!teamId) {
                actions.finishTogglingScanner(scanner.id)
                return
            }
            actions.setScannerEnabled(scanner.id, next)
            try {
                await visionScannersPartialUpdate(String(teamId), scanner.id, { enabled: next })
                refreshVisionQuota()
                lemonToast.success(`Scanner ${next ? 'enabled' : 'disabled'}`)
            } catch (error: any) {
                actions.setScannerEnabled(scanner.id, scanner.enabled)
                const verb = next ? 'enable' : 'disable'
                lemonToast.error(`Failed to ${verb} scanner${error.detail ? `: ${error.detail}` : ''}`)
            } finally {
                actions.finishTogglingScanner(scanner.id)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadUsageScanners()
    }),
])
