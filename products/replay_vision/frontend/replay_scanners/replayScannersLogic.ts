import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    visionScannersCreate,
    visionScannersDestroy,
    visionScannersList,
    visionScannersPartialUpdate,
} from '../generated/api'
import type { replayScannersLogicType } from './replayScannersLogicType'
import {
    ENABLED_OPTIONS,
    EnabledFilter,
    SCANNER_TYPE_OPTIONS,
    ScannerType,
    ReplayScanner,
    scannerFromApi,
    scannerToApiBody,
    scannersFromApi,
} from './types'

export interface ReplayScannersLogicProps {
    tabId: string
}

const ALL_ENABLED: EnabledFilter[] = ENABLED_OPTIONS.map((o) => o.value)
const ALL_SCANNER_TYPES: ScannerType[] = SCANNER_TYPE_OPTIONS.map((o) => o.value)

const csv = (values: string[]): string | undefined => (values.length > 0 ? values.join(',') : undefined)
const splitCsv = (value: unknown): string[] =>
    typeof value === 'string' && value.length > 0
        ? value
              .split(',')
              .map((v) => v.trim())
              .filter(Boolean)
        : []
const fromCsv = <T extends string>(value: unknown, allowed: readonly T[]): T[] =>
    splitCsv(value).filter((v): v is T => (allowed as readonly string[]).includes(v))

const createdByLabel = (user: NonNullable<ReplayScanner['created_by']>): string => {
    const name = [user.first_name, user.last_name].filter(Boolean).join(' ').trim()
    return name || user.email || `User ${user.id}`
}

export const replayScannersLogic = kea<replayScannersLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'replayScannersLogic']),
    props({} as ReplayScannersLogicProps),
    tabAwareScene(),

    actions({
        loadScanners: true,
        loadScannersSuccess: (scanners: ReplayScanner[]) => ({ scanners }),
        loadScannersFailure: (error: string) => ({ error }),
        deleteScanner: (id: string) => ({ id }),
        deleteScannerSuccess: (id: string) => ({ id }),
        duplicateScanner: (id: string) => ({ id }),
        duplicateScannerSuccess: (scanner: ReplayScanner) => ({ scanner }),
        toggleScannerEnabled: (id: string) => ({ id }),
        toggleScannerEnabledDone: (id: string) => ({ id }),
        revertScannerEnabled: (id: string) => ({ id }),
        setSearch: (search: string) => ({ search }),
        setEnabledFilter: (values: EnabledFilter[]) => ({ values }),
        setScannerTypeFilter: (scannerTypes: ScannerType[]) => ({ scannerTypes }),
        setChartDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setCreatedByFilter: (userIds: string[]) => ({ userIds }),
        clearFilters: true,
    }),

    reducers({
        scanners: [
            [] as ReplayScanner[],
            {
                loadScannersSuccess: (_, { scanners }) => scanners,
                deleteScannerSuccess: (state, { id }) => state.filter((l) => l.id !== id),
                duplicateScannerSuccess: (state, { scanner }) => [...state, scanner],
                toggleScannerEnabled: (state, { id }) =>
                    state.map((l) => (l.id === id ? { ...l, enabled: !l.enabled } : l)),
                revertScannerEnabled: (state, { id }) =>
                    state.map((l) => (l.id === id ? { ...l, enabled: !l.enabled } : l)),
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
        scannersLoading: [
            false,
            {
                loadScanners: () => true,
                loadScannersSuccess: () => false,
                loadScannersFailure: () => false,
            },
        ],
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
                clearFilters: () => '',
            },
        ],
        enabledFilter: [
            [] as EnabledFilter[],
            {
                setEnabledFilter: (_, { values }) => values,
                clearFilters: () => [],
            },
        ],
        scannerTypeFilter: [
            [] as ScannerType[],
            {
                setScannerTypeFilter: (_, { scannerTypes }) => scannerTypes,
                clearFilters: () => [],
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
        createdByFilter: [
            [] as string[],
            {
                setCreatedByFilter: (_, { userIds }) => userIds,
                clearFilters: () => [],
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
                const response = await visionScannersList(String(teamId))
                actions.loadScannersSuccess(scannersFromApi(response.results ?? []))
            } catch (error) {
                lemonToast.error(`Failed to load scanners: ${String(error)}`)
                actions.loadScannersFailure(String(error))
            }
        },

        deleteScanner: async ({ id }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                await visionScannersDestroy(String(teamId), id)
                actions.deleteScannerSuccess(id)
                lemonToast.success('Scanner deleted')
            } catch (error) {
                lemonToast.error(`Failed to delete scanner: ${String(error)}`)
            }
        },

        duplicateScanner: async ({ id }) => {
            const original = values.scanners.find((l) => l.id === id)
            if (!original) {
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            const duplicate: Record<string, unknown> = {
                name: `${original.name} (Copy)`,
                description: original.description,
                enabled: false,
                scanner_type: original.scanner_type,
                scanner_config: original.scanner_config,
                sampling_rate: original.sampling_rate,
                provider: original.provider,
                model: original.model,
                emits_signals: original.emits_signals,
            }
            if (original.query != null) {
                duplicate.query = original.query
            }
            try {
                const response = await visionScannersCreate(String(teamId), scannerToApiBody(duplicate))
                actions.duplicateScannerSuccess(scannerFromApi(response))
            } catch (error) {
                lemonToast.error(`Failed to duplicate scanner: ${String(error)}`)
            }
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
            try {
                await visionScannersPartialUpdate(String(teamId), id, { enabled: scanner.enabled })
                actions.toggleScannerEnabledDone(id)
            } catch (error) {
                lemonToast.error(`Failed to ${scanner.enabled ? 'enable' : 'disable'} scanner: ${String(error)}`)
                actions.revertScannerEnabled(id)
            }
        },
    })),

    selectors({
        hasActiveFilters: [
            (s) => [s.search, s.enabledFilter, s.scannerTypeFilter, s.createdByFilter],
            (search: string, enabled: EnabledFilter[], scannerTypes: ScannerType[], createdBy: string[]) =>
                search.trim().length > 0 || enabled.length > 0 || scannerTypes.length > 0 || createdBy.length > 0,
        ],
        createdByOptions: [
            (s) => [s.scanners],
            (scanners: ReplayScanner[]): { value: string; label: string }[] => {
                const byId = new Map<string, string>()
                for (const scanner of scanners) {
                    if (scanner.created_by) {
                        const id = String(scanner.created_by.id)
                        if (!byId.has(id)) {
                            byId.set(id, createdByLabel(scanner.created_by))
                        }
                    }
                }
                return Array.from(byId, ([value, label]) => ({ value, label })).sort((a, b) =>
                    a.label.localeCompare(b.label)
                )
            },
        ],
        filteredScanners: [
            (s) => [s.scanners, s.search, s.enabledFilter, s.scannerTypeFilter, s.createdByFilter],
            (
                scanners: ReplayScanner[],
                search: string,
                enabledValues: EnabledFilter[],
                scannerTypes: ScannerType[],
                createdBy: string[]
            ): ReplayScanner[] => {
                const q = search.trim().toLowerCase()
                return scanners.filter((l) => {
                    if (q) {
                        const haystack = [l.name, l.description ?? '', l.scanner_config.prompt].join(' ').toLowerCase()
                        if (!haystack.includes(q)) {
                            return false
                        }
                    }
                    if (enabledValues.length > 0) {
                        const visible: EnabledFilter = l.enabled ? 'enabled' : 'disabled'
                        if (!enabledValues.includes(visible)) {
                            return false
                        }
                    }
                    if (scannerTypes.length > 0 && !scannerTypes.includes(l.scanner_type)) {
                        return false
                    }
                    if (createdBy.length > 0) {
                        const id = l.created_by ? String(l.created_by.id) : null
                        if (!id || !createdBy.includes(id)) {
                            return false
                        }
                    }
                    return true
                })
            },
        ],
    }),

    tabAwareActionToUrl(({ values }) => {
        const buildUrl = (): [string, Record<string, string | undefined>, undefined, { replace: true }] => [
            urls.replayVision(),
            {
                ...router.values.searchParams,
                search: values.search || undefined,
                enabled: csv(values.enabledFilter),
                type: csv(values.scannerTypeFilter),
                created_by: csv(values.createdByFilter),
            },
            undefined,
            { replace: true },
        ]
        return {
            setSearch: buildUrl,
            setEnabledFilter: buildUrl,
            setScannerTypeFilter: buildUrl,
            setCreatedByFilter: buildUrl,
            clearFilters: buildUrl,
        }
    }),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.replayVision()]: (_, searchParams) => {
            const search = typeof searchParams.search === 'string' ? searchParams.search : ''
            if (search !== values.search) {
                actions.setSearch(search)
            }
            const enabledValues = fromCsv<EnabledFilter>(searchParams.enabled, ALL_ENABLED)
            if (csv(enabledValues) !== csv(values.enabledFilter)) {
                actions.setEnabledFilter(enabledValues)
            }
            const types = fromCsv<ScannerType>(searchParams.type, ALL_SCANNER_TYPES)
            if (csv(types) !== csv(values.scannerTypeFilter)) {
                actions.setScannerTypeFilter(types)
            }
            const createdBy = splitCsv(searchParams.created_by)
            if (csv(createdBy) !== csv(values.createdByFilter)) {
                actions.setCreatedByFilter(createdBy)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadScanners()
    }),
])
