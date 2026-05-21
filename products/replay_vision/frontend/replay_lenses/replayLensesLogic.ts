import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { visionLensesCreate, visionLensesDestroy, visionLensesList, visionLensesPartialUpdate } from '../generated/api'
import type { replayLensesLogicType } from './replayLensesLogicType'
import {
    ENABLED_OPTIONS,
    EnabledFilter,
    LENS_TYPE_OPTIONS,
    LensType,
    ReplayLens,
    VisionQuota,
    lensFromApi,
    lensToApiBody,
    lensesFromApi,
} from './types'

export interface ReplayLensesLogicProps {
    tabId: string
}

const ALL_ENABLED: EnabledFilter[] = ENABLED_OPTIONS.map((o) => o.value)
const ALL_LENS_TYPES: LensType[] = LENS_TYPE_OPTIONS.map((o) => o.value)

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

export const replayLensesLogic = kea<replayLensesLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_lenses', 'replayLensesLogic']),
    props({} as ReplayLensesLogicProps),
    tabAwareScene(),

    actions({
        loadLenses: true,
        loadLensesSuccess: (lenses: ReplayLens[]) => ({ lenses }),
        loadLensesFailure: (error: string) => ({ error }),
        loadQuota: true,
        loadQuotaSuccess: (quota: VisionQuota | null) => ({ quota }),
        deleteLens: (id: string) => ({ id }),
        deleteLensSuccess: (id: string) => ({ id }),
        duplicateLens: (id: string) => ({ id }),
        duplicateLensSuccess: (lens: ReplayLens) => ({ lens }),
        toggleLensEnabled: (id: string) => ({ id }),
        toggleLensEnabledSuccess: (id: string) => ({ id }),
        setSearch: (search: string) => ({ search }),
        setEnabledFilter: (values: EnabledFilter[]) => ({ values }),
        setLensTypeFilter: (lensTypes: LensType[]) => ({ lensTypes }),
        setUsageRangeDays: (days: 7 | 30 | 90) => ({ days }),
        clearFilters: true,
    }),

    reducers({
        lenses: [
            [] as ReplayLens[],
            {
                loadLensesSuccess: (_, { lenses }) => lenses,
                deleteLensSuccess: (state, { id }) => state.filter((l) => l.id !== id),
                duplicateLensSuccess: (state, { lens }) => [...state, lens],
                toggleLensEnabledSuccess: (state, { id }) =>
                    state.map((l) => (l.id === id ? { ...l, enabled: !l.enabled } : l)),
            },
        ],
        lensesLoading: [
            false,
            {
                loadLenses: () => true,
                loadLensesSuccess: () => false,
                loadLensesFailure: () => false,
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
        lensTypeFilter: [
            [] as LensType[],
            {
                setLensTypeFilter: (_, { lensTypes }) => lensTypes,
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
        loadLenses: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionLensesList(String(teamId))
                actions.loadLensesSuccess(lensesFromApi(response.results ?? []))
            } catch (error) {
                lemonToast.error(`Failed to load lenses: ${String(error)}`)
                actions.loadLensesFailure(String(error))
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

        deleteLens: async ({ id }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                await visionLensesDestroy(String(teamId), id)
                actions.deleteLensSuccess(id)
                lemonToast.success('Lens deleted')
            } catch (error) {
                lemonToast.error(`Failed to delete lens: ${String(error)}`)
            }
        },

        duplicateLens: async ({ id }) => {
            const original = values.lenses.find((l) => l.id === id)
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
                lens_type: original.lens_type,
                lens_config: original.lens_config,
                sampling_rate: original.sampling_rate,
                provider: original.provider,
                model: original.model,
                emits_signals: original.emits_signals,
            }
            if (original.query != null) {
                duplicate.query = original.query
            }
            try {
                const response = await visionLensesCreate(String(teamId), lensToApiBody(duplicate))
                actions.duplicateLensSuccess(lensFromApi(response))
            } catch (error) {
                lemonToast.error(`Failed to duplicate lens: ${String(error)}`)
            }
        },

        toggleLensEnabled: async ({ id }) => {
            const lens = values.lenses.find((l) => l.id === id)
            if (!lens) {
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                await visionLensesPartialUpdate(String(teamId), id, { enabled: !lens.enabled })
                actions.toggleLensEnabledSuccess(id)
            } catch (error) {
                lemonToast.error(`Failed to ${lens.enabled ? 'disable' : 'enable'} lens: ${String(error)}`)
            }
        },
    })),

    selectors({
        hasActiveFilters: [
            (s) => [s.search, s.enabledFilter, s.lensTypeFilter],
            (search: string, enabled: EnabledFilter[], lensTypes: LensType[]) =>
                search.trim().length > 0 || enabled.length > 0 || lensTypes.length > 0,
        ],
        filteredLenses: [
            (s) => [s.lenses, s.search, s.enabledFilter, s.lensTypeFilter],
            (
                lenses: ReplayLens[],
                search: string,
                enabledValues: EnabledFilter[],
                lensTypes: LensType[]
            ): ReplayLens[] => {
                const q = search.trim().toLowerCase()
                return lenses.filter((l) => {
                    if (q) {
                        const haystack = [l.name, l.description ?? '', l.lens_config.prompt].join(' ').toLowerCase()
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
                    if (lensTypes.length > 0 && !lensTypes.includes(l.lens_type)) {
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
                type: csv(values.lensTypeFilter),
            },
            undefined,
            { replace: true },
        ]
        return {
            setSearch: buildUrl,
            setEnabledFilter: buildUrl,
            setLensTypeFilter: buildUrl,
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
            const types = fromCsv<LensType>(searchParams.type, ALL_LENS_TYPES)
            if (csv(types) !== csv(values.lensTypeFilter)) {
                actions.setLensTypeFilter(types)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadLenses()
        actions.loadQuota()
    }),
])
