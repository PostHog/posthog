import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import {
    environmentVisionQuotaSpendSeriesRetrieve,
    visionScannersList,
    visionScannersPartialUpdate,
} from '../generated/api'
import type { VisionQuotaApi, VisionSpendSeriesApi } from '../generated/api.schemas'
import { refreshVisionQuota, visionQuotaLogic } from '../logics/visionQuotaLogic'
import { fleetContributions } from '../utils/quotaContributions'
import { currentQuotaScenario } from '../utils/quotaScenarios'
import { type SpendVerdict, spendVerdict } from '../utils/spendVerdict'
import type { ReplayScanner } from './types'

/** Settled credit spend per UTC day of the current billing period, oldest first, zero-filled through today. */
export type SpendSeries = VisionSpendSeriesApi['days']

interface visionUsageLogicValues {
    usageScanners: ReplayScanner[]
    usageScannersLoading: boolean
    togglingScannerIds: string[]
    spendSeries: SpendSeries | null
    spendSeriesLoading: boolean
    spendSeriesFailed: boolean
    quota: VisionQuotaApi | null
    displayQuota: VisionQuotaApi | null
    onFreePlan: boolean
    verdict: SpendVerdict
    usageRows: ReplayScanner[]
    hiddenScannerCount: number
    usageRowsTotalCredits: number
    resetsOn: dayjs.Dayjs | null
    daysToReset: number | null
    projectedTotalCredits: number | null
    projectedPctOfLimit: number | null
}

interface visionUsageLogicActions {
    loadUsageScanners: () => { value: true }
    loadUsageScannersSuccess: (usageScanners: ReplayScanner[]) => { usageScanners: ReplayScanner[] }
    toggleScannerEnabled: (scanner: ReplayScanner) => { scanner: ReplayScanner }
    setScannerEnabled: (id: string, enabled: boolean) => { id: string; enabled: boolean }
    finishTogglingScanner: (id: string) => { id: string }
    loadSpendSeries: () => void
    loadSpendSeriesSuccess: (spendSeries: SpendSeries | null) => { spendSeries: SpendSeries | null }
    loadSpendSeriesFailure: (error: string) => { error: string }
    loadQuotaSuccess: (quota: VisionQuotaApi | null) => { quota: VisionQuotaApi | null }
}

export type visionUsageLogicType = MakeLogicType<visionUsageLogicValues, visionUsageLogicActions>

// Loads the whole team's scanners ordered by spend for the Usage tab and the overview's
// usage bridge. Separate from replayScannersLogic so the list tab's filters and
// pagination never leak into usage math. Loaded manually rather than via kea-loaders so a
// per-row enable toggle can update the list optimistically without a refetch.
export const visionUsageLogic = kea<visionUsageLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'visionUsageLogic']),
    connect(() => ({
        values: [visionQuotaLogic, ['quota', 'displayQuota', 'onFreePlan']],
        actions: [visionQuotaLogic, ['loadQuotaSuccess']],
    })),
    actions({
        loadUsageScanners: true,
        loadUsageScannersSuccess: (usageScanners: ReplayScanner[]) => ({ usageScanners }),
        toggleScannerEnabled: (scanner: ReplayScanner) => ({ scanner }),
        setScannerEnabled: (id: string, enabled: boolean) => ({ id, enabled }),
        finishTogglingScanner: (id: string) => ({ id }),
    }),
    loaders(({ values }) => ({
        spendSeries: [
            null as SpendSeries | null,
            {
                loadSpendSeries: async (): Promise<SpendSeries | null> => {
                    const scenario = currentQuotaScenario()
                    if (scenario) {
                        return scenario.dailySpend ?? []
                    }
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId || !values.quota?.period_start) {
                        return null
                    }
                    const response = await environmentVisionQuotaSpendSeriesRetrieve(String(teamId))
                    return response.days
                },
            },
        ],
    })),
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
        togglingScannerIds: [
            [] as string[],
            {
                toggleScannerEnabled: (state, { scanner }) =>
                    state.includes(scanner.id) ? state : [...state, scanner.id],
                finishTogglingScanner: (state, { id }) => state.filter((toggling) => toggling !== id),
            },
        ],
        spendSeriesFailed: [
            false,
            {
                loadSpendSeries: () => false,
                loadSpendSeriesFailure: () => true,
            },
        ],
    }),
    selectors({
        verdict: [
            (s) => [s.displayQuota, s.onFreePlan],
            (quota: VisionQuotaApi | null, onFreePlan: boolean): SpendVerdict =>
                spendVerdict(quota, fleetContributions(quota), { onFreePlan }),
        ],
        // Rows that cost something this period or are set to: idle disabled scanners only add noise.
        usageRows: [
            (s) => [s.usageScanners],
            (usageScanners: ReplayScanner[]): ReplayScanner[] =>
                usageScanners.filter(
                    (scanner) =>
                        scanner.credits_this_month > 0 ||
                        (scanner.enabled && (scanner.estimated_monthly_credits ?? 0) > 0)
                ),
        ],
        hiddenScannerCount: [
            (s) => [s.usageScanners, s.usageRows],
            (usageScanners: ReplayScanner[], usageRows: ReplayScanner[]): number =>
                usageScanners.length - usageRows.length,
        ],
        usageRowsTotalCredits: [
            (s) => [s.usageRows],
            (usageRows: ReplayScanner[]): number => usageRows.reduce((sum, s) => sum + s.credits_this_month, 0),
        ],
        resetsOn: [
            (s) => [s.displayQuota],
            (quota: VisionQuotaApi | null): dayjs.Dayjs | null => (quota?.period_end ? dayjs(quota.period_end) : null),
        ],
        daysToReset: [
            (s) => [s.resetsOn],
            (resetsOn: dayjs.Dayjs | null): number | null =>
                resetsOn ? Math.max(resetsOn.startOf('day').diff(dayjs().startOf('day'), 'day'), 0) : null,
        ],
        // What the period will actually cost: spend stops at the limit, so demand past it is not billed.
        projectedTotalCredits: [
            (s) => [s.displayQuota, s.verdict],
            (quota: VisionQuotaApi | null, verdict: SpendVerdict): number | null => {
                if (!quota || verdict.projectedDemandCredits === null) {
                    return null
                }
                return verdict.hasCap
                    ? Math.min(verdict.projectedDemandCredits, quota.credit_limit ?? 0)
                    : verdict.projectedDemandCredits
            },
        ],
        projectedPctOfLimit: [
            (s) => [s.displayQuota, s.projectedTotalCredits],
            (quota: VisionQuotaApi | null, projectedTotalCredits: number | null): number | null =>
                quota && projectedTotalCredits !== null && (quota.credit_limit ?? 0) > 0
                    ? Math.round((projectedTotalCredits / (quota.credit_limit ?? 1)) * 100)
                    : null,
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        loadUsageScanners: async () => {
            const scenario = currentQuotaScenario()
            if (scenario?.usageScanners) {
                actions.loadUsageScannersSuccess(scenario.usageScanners as unknown as ReplayScanner[])
                return
            }
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
                // Keep the list already shown; the table's own empty/loaded state stays consistent.
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
        // The chart is period-scoped, so it can only run once the quota names the period. Quota
        // refetches after scanner toggles keep the same period, and settled daily spend doesn't
        // move with them, so a loaded series is only refreshed when the period changes.
        loadQuotaSuccess: ({ quota }) => {
            const periodStart = quota?.period_start
            if (periodStart && !values.spendSeriesLoading && periodStart !== cache.spendSeriesPeriodStart) {
                actions.loadSpendSeries()
            }
        },
        loadSpendSeries: () => {
            // Recorded on request rather than success so a failed period is not retried on every quota refetch.
            cache.spendSeriesPeriodStart = values.quota?.period_start
        },
    })),
    afterMount(({ actions, values }) => {
        actions.loadUsageScanners()
        if (values.quota && !values.spendSeriesLoading) {
            actions.loadSpendSeries()
        }
    }),
])
