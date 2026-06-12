import equal from 'fast-deep-equal'
import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    visionScannersCreatorsRetrieve,
    visionScannersDestroy,
    visionScannersList,
    visionScannersPartialUpdate,
    visionScannersStatsRetrieve,
} from '../generated/api'
import type { ScannerStatsResponseApi, UserBasicApi, VisionScannersListParams } from '../generated/api.schemas'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import type { replayScannersLogicType } from './replayScannersLogicType'
import {
    ENABLED_OPTIONS,
    EnabledFilter,
    SCANNER_TYPE_OPTIONS,
    ScannerType,
    ReplayScanner,
    createdByLabel,
    scannersFromApi,
} from './types'

// Filter fields whose change shifts the result set; auto-reset page unless the caller passes a new one.
const FILTER_RESET_KEYS = ['search', 'enabledFilter', 'scannerTypeFilter', 'createdByFilter', 'sort'] as const

// Keep in sync with `SCANNER_ORDER_FIELDS` in products/replay_vision/backend/api/scanners.py.
export const SORTABLE_COLUMN_KEYS = [
    'name',
    'enabled',
    'scanner_type',
    'sampling_rate',
    'created_by',
    'created_at',
    'updated_at',
] as const
export type ScannerOrderKey = (typeof SORTABLE_COLUMN_KEYS)[number]

export interface ScannersSorting {
    columnKey: ScannerOrderKey
    order: 1 | -1
}

export const SCANNERS_PAGE_SIZE = 50
const ALL_ENABLED: EnabledFilter[] = ENABLED_OPTIONS.map((o) => o.value)
const ALL_SCANNER_TYPES: ScannerType[] = SCANNER_TYPE_OPTIONS.map((o) => o.value)
const DEFAULT_SORT: ScannersSorting = { columnKey: 'created_at', order: -1 }

export interface ScannersFilters {
    search: string
    enabledFilter: EnabledFilter[]
    scannerTypeFilter: ScannerType[]
    createdByFilter: string[]
    page: number
    sort: ScannersSorting | null
}

export const DEFAULT_FILTERS: ScannersFilters = {
    search: '',
    enabledFilter: [],
    scannerTypeFilter: [],
    createdByFilter: [],
    page: 1,
    sort: DEFAULT_SORT,
}

const csv = (values: string[]): string | undefined => (values.length > 0 ? values.join(',') : undefined)
const splitCsv = (value: unknown): string[] =>
    // The router coerces a single numeric param to a number, so coerce back to a string before splitting.
    value === null || value === undefined || value === ''
        ? []
        : String(value)
              .split(',')
              .map((v) => v.trim())
              .filter(Boolean)
const fromCsv = <T extends string>(value: unknown, allowed: readonly T[]): T[] =>
    splitCsv(value).filter((v): v is T => (allowed as readonly string[]).includes(v))

export function resolveScannerOrderByKey(columnKey: string): ScannerOrderKey | null {
    return (SORTABLE_COLUMN_KEYS as readonly string[]).includes(columnKey) ? (columnKey as ScannerOrderKey) : null
}

export function buildScannerListParams(
    values: {
        search: string
        enabledFilter: EnabledFilter[]
        scannerTypeFilter: ScannerType[]
        createdByFilter: string[]
        scannersSort: ScannersSorting | null
    },
    limit?: number,
    offset?: number
): VisionScannersListParams {
    const params: VisionScannersListParams = {}
    if (limit !== undefined) {
        params.limit = limit
    }
    if (offset !== undefined && offset > 0) {
        params.offset = offset
    }
    const trimmed = values.search.trim()
    if (trimmed.length > 0) {
        params.search = trimmed
    }
    if (values.enabledFilter.length > 0) {
        params.enabled = values.enabledFilter.join(',')
    }
    if (values.scannerTypeFilter.length > 0) {
        params.scanner_type = values.scannerTypeFilter.join(',')
    }
    if (values.createdByFilter.length > 0) {
        params.created_by = values.createdByFilter.join(',')
    }
    if (values.scannersSort) {
        const orderKey = resolveScannerOrderByKey(values.scannersSort.columnKey)
        if (orderKey) {
            params.order_by = values.scannersSort.order === -1 ? `-${orderKey}` : orderKey
        }
    }
    return params
}

function parseSortParam(value: unknown): ScannersSorting | null {
    if (typeof value !== 'string' || value.length === 0) {
        return null
    }
    const descending = value.startsWith('-')
    const key = resolveScannerOrderByKey(descending ? value.slice(1) : value)
    if (!key) {
        return null
    }
    return { columnKey: key, order: descending ? -1 : 1 }
}

export const replayScannersLogic = kea<replayScannersLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'replayScannersLogic']),

    actions({
        loadScanners: true,
        loadScannersSuccess: (scanners: ReplayScanner[], total: number) => ({ scanners, total }),
        loadScannersFailure: (error: string) => ({ error }),
        loadCreators: true,
        loadCreatorsSuccess: (creators: UserBasicApi[]) => ({ creators }),
        loadCreatorsFailure: true,
        loadScannerStats: true,
        loadScannerStatsSuccess: (stats: ScannerStatsResponseApi) => ({ stats }),
        loadScannerStatsFailure: true,
        deleteScanner: (id: string) => ({ id }),
        deleteScannerSuccess: (id: string) => ({ id }),
        toggleScannerEnabled: (id: string) => ({ id }),
        toggleScannerEnabledDone: (id: string) => ({ id }),
        revertScannerEnabled: (id: string) => ({ id }),
        setChartDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setScannersFilters: (filters: Partial<ScannersFilters>, replace: boolean = false) => ({ filters, replace }),
        clearFilters: true,
    }),

    reducers({
        scanners: [
            [] as ReplayScanner[],
            {
                loadScannersSuccess: (_, { scanners }) => scanners,
                deleteScannerSuccess: (state, { id }) => state.filter((l) => l.id !== id),
                toggleScannerEnabled: (state, { id }) =>
                    state.map((l) => (l.id === id ? { ...l, enabled: !l.enabled } : l)),
                revertScannerEnabled: (state, { id }) =>
                    state.map((l) => (l.id === id ? { ...l, enabled: !l.enabled } : l)),
            },
        ],
        scannersTotal: [
            0,
            {
                loadScannersSuccess: (_, { total }) => total,
            },
        ],
        filters: [
            DEFAULT_FILTERS,
            {
                setScannersFilters: (state, { filters, replace }) => {
                    const next: ScannersFilters = replace
                        ? { ...DEFAULT_FILTERS, ...filters }
                        : { ...state, ...filters }
                    const resets = !('page' in filters) && FILTER_RESET_KEYS.some((k) => k in filters)
                    return resets ? { ...next, page: 1 } : next
                },
                clearFilters: (state) => ({
                    ...state,
                    search: '',
                    enabledFilter: [],
                    scannerTypeFilter: [],
                    createdByFilter: [],
                    page: 1,
                }),
            },
        ],
        togglingIds: [
            [] as string[],
            {
                toggleScannerEnabled: (state, { id }) => [...state, id],
                toggleScannerEnabledDone: (state, { id }) => state.filter((i) => i !== id),
                revertScannerEnabled: (state, { id }) => state.filter((i) => i !== id),
            },
        ],
        creators: [
            [] as UserBasicApi[],
            {
                loadCreatorsSuccess: (_, { creators }) => creators,
            },
        ],
        scannerStats: [
            null as ScannerStatsResponseApi | null,
            {
                loadScannerStatsSuccess: (_, { stats }) => stats,
            },
        ],
        scannersLoading: [
            false,
            {
                loadScanners: () => true,
                loadScannersSuccess: () => false,
                loadScannersFailure: () => false,
            },
        ],
        scannerStatsLoading: [
            false,
            {
                loadScannerStats: () => true,
                loadScannerStatsSuccess: () => false,
                loadScannerStatsFailure: () => false,
            },
        ],
        chartDateFrom: [
            '-30d' as string | null,
            {
                setChartDateRange: (_, { dateFrom }) => dateFrom,
            },
        ],
        chartDateTo: [
            null as string | null,
            {
                setChartDateRange: (_, { dateTo }) => dateTo,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadScanners: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const { filters } = values
                const offset = (filters.page - 1) * SCANNERS_PAGE_SIZE
                const params = buildScannerListParams(
                    {
                        search: filters.search,
                        enabledFilter: filters.enabledFilter,
                        scannerTypeFilter: filters.scannerTypeFilter,
                        createdByFilter: filters.createdByFilter,
                        scannersSort: filters.sort,
                    },
                    SCANNERS_PAGE_SIZE,
                    offset
                )
                const response = await visionScannersList(String(teamId), params)
                actions.loadScannersSuccess(scannersFromApi(response.results ?? []), response.count ?? 0)
            } catch (error: any) {
                lemonToast.error(`Failed to load scanners${error.detail ? `: ${error.detail}` : ''}`)
                actions.loadScannersFailure(String(error))
            }
        },

        // Any change that affects the result set has to refetch.
        setScannersFilters: () => actions.loadScanners(),
        clearFilters: () => actions.loadScanners(),

        deleteScanner: async ({ id }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            // Deleting an enabled scanner removes its known contribution from the fleet sum — exact, so apply it now.
            const scanner = values.scanners.find((s) => s.id === id)
            const delta = scanner?.enabled ? -(scanner.estimated_monthly_observations ?? 0) : 0
            visionQuotaLogic.findMounted()?.actions.adjustProjectedMonthly(delta)
            try {
                await visionScannersDestroy(String(teamId), id)
                actions.deleteScannerSuccess(id)
                lemonToast.success('Scanner deleted')
            } catch (error: any) {
                visionQuotaLogic.findMounted()?.actions.adjustProjectedMonthly(-delta)
                lemonToast.error(`Failed to delete scanner${error.detail ? `: ${error.detail}` : ''}`)
            }
        },

        loadCreators: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionScannersCreatorsRetrieve(String(teamId))
                actions.loadCreatorsSuccess(response.creators ?? [])
            } catch {
                actions.loadCreatorsFailure()
            }
        },

        loadScannerStats: async (_, breakpoint) => {
            // Debounce so a burst of mutations (rapid toggles, bulk delete) coalesces into one refetch.
            await breakpoint(50)
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionScannersStatsRetrieve(String(teamId))
                actions.loadScannerStatsSuccess(response)
            } catch {
                actions.loadScannerStatsFailure()
            }
        },

        // Refetch after any mutation so the page + creator dropdown + team-wide stats + quota meter stay accurate.
        deleteScannerSuccess: () => {
            actions.loadScanners()
            actions.loadCreators()
            actions.loadScannerStats()
            visionQuotaLogic.findMounted()?.actions.loadQuota()
        },
        toggleScannerEnabledDone: () => {
            actions.loadScannerStats()
            visionQuotaLogic.findMounted()?.actions.loadQuota()
        },

        toggleScannerEnabled: async ({ id }) => {
            // The reducer has already flipped `enabled` optimistically, so this reflects the new target state.
            const scanner = values.scanners.find((l) => l.id === id)
            if (!scanner) {
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.revertScannerEnabled(id)
                return
            }
            // The stored estimate is kept ≤24h fresh even while disabled, so the projection shift is known up front.
            const estimate = scanner.estimated_monthly_observations ?? 0
            const delta = scanner.enabled ? estimate : -estimate
            visionQuotaLogic.findMounted()?.actions.adjustProjectedMonthly(delta)
            try {
                await visionScannersPartialUpdate(String(teamId), id, { enabled: scanner.enabled })
                actions.toggleScannerEnabledDone(id)
            } catch (error: any) {
                const verb = scanner.enabled ? 'enable' : 'disable'
                lemonToast.error(`Failed to ${verb} scanner${error.detail ? `: ${error.detail}` : ''}`)
                visionQuotaLogic.findMounted()?.actions.adjustProjectedMonthly(-delta)
                actions.revertScannerEnabled(id)
            }
        },
    })),

    selectors({
        search: [(s) => [s.filters], (filters: ScannersFilters) => filters.search],
        enabledFilter: [(s) => [s.filters], (filters: ScannersFilters) => filters.enabledFilter],
        scannerTypeFilter: [(s) => [s.filters], (filters: ScannersFilters) => filters.scannerTypeFilter],
        createdByFilter: [(s) => [s.filters], (filters: ScannersFilters) => filters.createdByFilter],
        scannersPage: [(s) => [s.filters], (filters: ScannersFilters) => filters.page],
        scannersSort: [(s) => [s.filters], (filters: ScannersFilters) => filters.sort],
        hasActiveFilters: [
            (s) => [s.search, s.enabledFilter, s.scannerTypeFilter, s.createdByFilter],
            (search: string, enabled: EnabledFilter[], scannerTypes: ScannerType[], createdBy: string[]) =>
                search.trim().length > 0 || enabled.length > 0 || scannerTypes.length > 0 || createdBy.length > 0,
        ],
        createdByOptions: [
            (s) => [s.creators, s.createdByFilter],
            (creators: UserBasicApi[], selectedIds: string[]): { value: string; label: string }[] => {
                const byId = new Map<string, string>()
                for (const user of creators) {
                    byId.set(String(user.id), createdByLabel(user))
                }
                // Surface a selected-but-unknown id (e.g. shared URL) so the user can deselect it.
                for (const id of selectedIds) {
                    if (!byId.has(id)) {
                        byId.set(id, `User ${id}`)
                    }
                }
                return Array.from(byId, ([value, label]) => ({ value, label })).sort((a, b) =>
                    a.label.localeCompare(b.label)
                )
            },
        ],
    }),

    trackedActionToUrl(({ values }) => {
        const buildUrl = (): [string, Record<string, string | undefined>, undefined, { replace: true }] => {
            const { filters } = values
            const sortParam =
                filters.sort &&
                !(filters.sort.columnKey === DEFAULT_SORT.columnKey && filters.sort.order === DEFAULT_SORT.order)
                    ? `${filters.sort.order === -1 ? '-' : ''}${filters.sort.columnKey}`
                    : undefined
            return [
                urls.replayVision(),
                {
                    ...router.values.searchParams,
                    search: filters.search || undefined,
                    enabled: csv(filters.enabledFilter),
                    type: csv(filters.scannerTypeFilter),
                    created_by: csv(filters.createdByFilter),
                    page: filters.page > 1 ? String(filters.page) : undefined,
                    sort: sortParam,
                },
                undefined,
                { replace: true },
            ]
        }
        return {
            setScannersFilters: buildUrl,
            clearFilters: buildUrl,
        }
    }),

    urlToAction(({ actions, values, cache }) => ({
        [urls.replayVision()]: (_, searchParams) => {
            const pageRaw = Number(searchParams.page ?? 1)
            const parsed: ScannersFilters = {
                search: typeof searchParams.search === 'string' ? searchParams.search : '',
                enabledFilter: fromCsv<EnabledFilter>(searchParams.enabled, ALL_ENABLED),
                scannerTypeFilter: fromCsv<ScannerType>(searchParams.type, ALL_SCANNER_TYPES),
                createdByFilter: splitCsv(searchParams.created_by),
                page: Number.isFinite(pageRaw) ? Math.max(1, pageRaw) : 1,
                sort: parseSortParam(searchParams.sort) ?? DEFAULT_SORT,
            }
            const changed = !equal(parsed, values.filters)
            if (changed) {
                actions.setScannersFilters(parsed, true)
            } else if (!cache.initialLoad) {
                // urlToAction always fires on mount; without URL params it short-circuits, so kick the first fetch here.
                actions.loadScanners()
            }
            cache.initialLoad = true
        },
    })),

    afterMount(({ actions }) => {
        actions.loadCreators()
        actions.loadScannerStats()
    }),
])
