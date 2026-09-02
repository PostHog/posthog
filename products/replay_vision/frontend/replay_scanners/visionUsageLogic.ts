import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { performQuery } from '~/queries/query'
import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, PropertyFilterType, PropertyOperator } from '~/types'

import { visionScannersList, visionScannersPartialUpdate } from '../generated/api'
import type { VisionQuotaApi } from '../generated/api.schemas'
import { refreshVisionQuota, visionQuotaLogic } from '../logics/visionQuotaLogic'
import { currentQuotaScenario } from '../utils/quotaScenarios'
import { OBSERVATION_CREDITS_BY_MODEL, type ReplayScanner } from './types'

const RECORDING_OBSERVED_EVENT = '$recording_observed'

// Counted per model and priced in the formula: events predating the `credits` property sum to zero.
const SPEND_MODEL_PRICES = Object.entries(OBSERVATION_CREDITS_BY_MODEL)

/** Daily credit spend for the current billing period; index 0 is the period's first day. */
export type SpendSeries = number[]

interface visionUsageLogicValues {
    usageScanners: ReplayScanner[]
    usageScannersLoading: boolean
    togglingScannerIds: string[]
    spendSeries: SpendSeries | null
    spendSeriesLoading: boolean
    quota: VisionQuotaApi | null
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
        values: [visionQuotaLogic, ['quota']],
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
                    const periodStart = values.quota?.period_start
                    if (!periodStart) {
                        return null
                    }
                    const query: TrendsQuery = {
                        kind: NodeKind.TrendsQuery,
                        series: SPEND_MODEL_PRICES.map(([model]) => ({
                            kind: NodeKind.EventsNode,
                            event: RECORDING_OBSERVED_EVENT,
                            math: BaseMathType.TotalCount,
                            properties: [
                                {
                                    type: PropertyFilterType.Event,
                                    key: 'model_used',
                                    operator: PropertyOperator.Exact,
                                    value: model,
                                },
                            ],
                        })),
                        trendsFilter: {
                            formula: SPEND_MODEL_PRICES.map(
                                ([, credits], index) => `${String.fromCharCode(65 + index)}*${credits}`
                            ).join(' + '),
                        },
                        interval: 'day',
                        dateRange: {
                            date_from: dayjs(periodStart).format('YYYY-MM-DD'),
                            date_to: dayjs().format('YYYY-MM-DD'),
                        },
                    }
                    const response = await performQuery(query)
                    const result = (response as { results?: { data?: number[] }[] }).results?.[0]
                    return result?.data ?? []
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
        // The chart is period-scoped, so it can only run once the quota names the period. Quota
        // refetches after scanner toggles keep the same period, and daily spend history doesn't
        // move with them, so a loaded series is only refreshed when the period changes.
        loadQuotaSuccess: ({ quota }) => {
            if (
                values.spendSeries === null ||
                (quota?.period_start && quota.period_start !== cache.spendSeriesPeriodStart)
            ) {
                actions.loadSpendSeries()
            }
        },
        loadSpendSeriesSuccess: () => {
            cache.spendSeriesPeriodStart = values.quota?.period_start
        },
    })),
    afterMount(({ actions, values }) => {
        actions.loadUsageScanners()
        if (values.quota) {
            actions.loadSpendSeries()
        }
    }),
])
