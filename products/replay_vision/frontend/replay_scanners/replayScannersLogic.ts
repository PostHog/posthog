import { actions, afterMount, isBreakpoint, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
import { objectsEqual } from 'lib/utils/objects'
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
import { refreshVisionQuota, visionQuotaLogic } from '../logics/visionQuotaLogic'
import { csvParam, parseCsvParam, parseSortParam, serializeSortParam } from '../utils/urlParams'
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

export const replayScannersLogic = kea<replayScannersLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'replayScannersLogic']),

    actions({
        loadScanners: true,
        // Declared here so the actions stay zero-arg despite the loaders' payload/breakpoint parameters.
        loadCreators: true,
        loadScannerStats: true,
        loadScannersSuccess: (scanners: ReplayScanner[], total: number) => ({ scanners, total }),
        loadScannersFailure: (error: string) => ({ error }),
        deleteScanner: (id: string) => ({ id }),
        deleteScannerSuccess: (id: string) => ({ id }),
        setScannerDeleting: (id: string, deleting: boolean) => ({ id, deleting }),
        toggleScannerEnabled: (id: string) => ({ id }),
        toggleScannerEnabledDone: (id: string) => ({ id }),
        revertScannerEnabled: (id: string) => ({ id }),
        setChartDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setScannersFilters: (filters: Partial<ScannersFilters>, replace: boolean = false) => ({ filters, replace }),
        clearFilters: true,
    }),

    loaders(({ values }) => ({
        creators: [
            [] as UserBasicApi[],
            {
                loadCreators: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return values.creators
                    }
                    try {
                        const response = await visionScannersCreatorsRetrieve(String(teamId))
                        return response.creators ?? []
                    } catch {
                        return values.creators
                    }
                },
            },
        ],
        scannerStats: [
            null as ScannerStatsResponseApi | null,
            {
                loadScannerStats: async (_, breakpoint) => {
                    // Debounce so a burst of mutations (rapid toggles, bulk delete) coalesces into one refetch.
                    await breakpoint(50)
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return values.scannerStats
                    }
                    try {
                        return await visionScannersStatsRetrieve(String(teamId))
                    } catch {
                        return values.scannerStats
                    }
                },
            },
        ],
    })),

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
        deletingIds: [
            [] as string[],
            {
                setScannerDeleting: (state, { id, deleting }) =>
                    deleting ? [...state, id] : state.filter((i) => i !== id),
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
        loadScanners: async (_, breakpoint) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.loadScannersFailure('No team in context') // Clear the loading flag; a bare return spins forever.
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
                // Drop out-of-order responses — the most recent filter/page change owns the table.
                breakpoint()
                const results = response.results ?? []
                const count = response.count ?? 0
                // A shrunken set (delete, narrowed filter, concurrent change) can strand an out-of-range page.
                if (results.length === 0 && count > 0 && filters.page > 1) {
                    actions.setScannersFilters({ page: Math.ceil(count / SCANNERS_PAGE_SIZE) })
                    return
                }
                actions.loadScannersSuccess(scannersFromApi(results), count)
            } catch (error: any) {
                if (error instanceof Error && isBreakpoint(error)) {
                    throw error
                }
                lemonToast.error(`Failed to load scanners${error.detail ? `: ${error.detail}` : ''}`)
                actions.loadScannersFailure(String(error))
            }
        },

        // Refetch on any result-set change; debounce live search keystrokes only — URL restores must load immediately.
        setScannersFilters: async ({ filters, replace }, breakpoint) => {
            if (filters.search !== undefined && !replace) {
                await breakpoint(300)
            }
            actions.loadScanners()
        },
        clearFilters: () => actions.loadScanners(),

        deleteScanner: async ({ id }) => {
            const teamId = teamLogic.values.currentTeamId
            // The in-flight guard keeps a double-click from double-applying the optimistic quota delta below.
            if (!teamId || values.deletingIds.includes(id)) {
                return
            }
            actions.setScannerDeleting(id, true)
            // Deleting an enabled scanner removes its known contribution from the fleet sum — exact, so apply it now.
            const scanner = values.scanners.find((s) => s.id === id)
            const delta = scanner?.enabled ? -(scanner.estimated_monthly_credits ?? 0) : 0
            visionQuotaLogic.findMounted()?.actions.adjustProjectedMonthly(delta)
            try {
                await visionScannersDestroy(String(teamId), id)
                actions.deleteScannerSuccess(id)
                lemonToast.success('Scanner deleted')
            } catch (error: any) {
                visionQuotaLogic.findMounted()?.actions.adjustProjectedMonthly(-delta)
                lemonToast.error(`Failed to delete scanner${error.detail ? `: ${error.detail}` : ''}`)
            } finally {
                actions.setScannerDeleting(id, false)
            }
        },

        // Refetch after any mutation so the page + creator dropdown + team-wide stats + quota meter stay accurate.
        deleteScannerSuccess: () => {
            actions.loadScanners()
            actions.loadCreators()
            actions.loadScannerStats()
            refreshVisionQuota()
        },
        toggleScannerEnabledDone: () => {
            actions.loadScannerStats()
            refreshVisionQuota()
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
            const estimate = scanner.estimated_monthly_credits ?? 0
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
            const sortParam = serializeSortParam(filters.sort, DEFAULT_SORT)
            return [
                urls.replayVision(),
                {
                    ...router.values.searchParams,
                    search: filters.search || undefined,
                    enabled: csvParam(filters.enabledFilter),
                    type: csvParam(filters.scannerTypeFilter),
                    created_by: csvParam(filters.createdByFilter),
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
                enabledFilter: parseCsvParam<EnabledFilter>(searchParams.enabled, ALL_ENABLED),
                scannerTypeFilter: parseCsvParam<ScannerType>(searchParams.type, ALL_SCANNER_TYPES),
                createdByFilter: parseCsvParam(searchParams.created_by),
                page: Number.isFinite(pageRaw) ? Math.max(1, pageRaw) : 1,
                sort: parseSortParam(searchParams.sort, resolveScannerOrderByKey) ?? DEFAULT_SORT,
            }
            const changed = !objectsEqual(parsed, values.filters)
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
