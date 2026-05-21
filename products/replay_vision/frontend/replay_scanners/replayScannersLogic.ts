import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
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
    VisionQuota,
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
const fromCsv = <T extends string>(value: unknown, allowed: readonly T[]): T[] => {
    if (typeof value !== 'string' || value.length === 0) {
        return []
    }
    return value
        .split(',')
        .map((v) => v.trim())
        .filter((v): v is T => (allowed as readonly string[]).includes(v))
}

export const replayScannersLogic = kea<replayScannersLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'replayScannersLogic']),
    props({} as ReplayScannersLogicProps),
    tabAwareScene(),

    actions({
        loadScanners: true,
        loadScannersSuccess: (scanners: ReplayScanner[]) => ({ scanners }),
        loadScannersFailure: (error: string) => ({ error }),
        loadQuota: true,
        loadQuotaSuccess: (quota: VisionQuota | null) => ({ quota }),
        deleteScanner: (id: string) => ({ id }),
        deleteScannerSuccess: (id: string) => ({ id }),
        duplicateScanner: (id: string) => ({ id }),
        duplicateScannerSuccess: (scanner: ReplayScanner) => ({ scanner }),
        toggleScannerEnabled: (id: string) => ({ id }),
        toggleScannerEnabledSuccess: (id: string) => ({ id }),
        setSearch: (search: string) => ({ search }),
        setEnabledFilter: (values: EnabledFilter[]) => ({ values }),
        setScannerTypeFilter: (scannerTypes: ScannerType[]) => ({ scannerTypes }),
        setUsageRangeDays: (days: 7 | 30 | 90) => ({ days }),
        clearFilters: true,
    }),

    reducers({
        scanners: [
            [] as ReplayScanner[],
            {
                loadScannersSuccess: (_, { scanners }) => scanners,
                deleteScannerSuccess: (state, { id }) => state.filter((l) => l.id !== id),
                duplicateScannerSuccess: (state, { scanner }) => [...state, scanner],
                toggleScannerEnabledSuccess: (state, { id }) =>
                    state.map((l) => (l.id === id ? { ...l, enabled: !l.enabled } : l)),
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
        quota: [
            null as VisionQuota | null,
            {
                loadQuotaSuccess: (_, { quota }) => quota,
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
        usageRangeDays: [
            30 as 7 | 30 | 90,
            {
                setUsageRangeDays: (_, { days }) => days,
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

        loadQuota: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                // nosemgrep: prefer-codegen-api
                const response = await api.get(`/api/environments/${teamId}/vision/quota/`)
                actions.loadQuotaSuccess(response)
            } catch {
                actions.loadQuotaSuccess(null)
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
            const scanner = values.scanners.find((l) => l.id === id)
            if (!scanner) {
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                await visionScannersPartialUpdate(String(teamId), id, { enabled: !scanner.enabled })
                actions.toggleScannerEnabledSuccess(id)
            } catch (error) {
                lemonToast.error(`Failed to ${scanner.enabled ? 'disable' : 'enable'} scanner: ${String(error)}`)
            }
        },
    })),

    selectors({
        hasActiveFilters: [
            (s) => [s.search, s.enabledFilter, s.scannerTypeFilter],
            (search: string, enabled: EnabledFilter[], scannerTypes: ScannerType[]) =>
                search.trim().length > 0 || enabled.length > 0 || scannerTypes.length > 0,
        ],
        filteredScanners: [
            (s) => [s.scanners, s.search, s.enabledFilter, s.scannerTypeFilter],
            (
                scanners: ReplayScanner[],
                search: string,
                enabledValues: EnabledFilter[],
                scannerTypes: ScannerType[]
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
            },
            undefined,
            { replace: true },
        ]
        return {
            setSearch: buildUrl,
            setEnabledFilter: buildUrl,
            setScannerTypeFilter: buildUrl,
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
        },
    })),

    afterMount(({ actions }) => {
        actions.loadScanners()
        actions.loadQuota()
    }),
])
