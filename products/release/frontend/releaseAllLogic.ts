import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    listeners,
    path,
    reducers,
    selectors,
} from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'lib/posthog-typed'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'

import { earlyAccessFeatureList } from 'products/early_access_features/frontend/generated/api'
import { experimentsList } from 'products/experiments/frontend/generated/api'

import { releasesCatalogFlagsRetrieve, releasesCatalogReleasesRetrieve } from './generated/api'
import { releaseImportLogic } from './releaseImportLogic'
import { releaseLogic } from './releaseLogic'
import { ReleaseRow, STAGE_LABEL } from './releaseUtils'

export const ALL_PAGE_SIZE = 50
const SEARCH_DEBOUNCE_MS = 250

export type ReleaseAllType = 'release' | 'feature_flag' | 'experiment' | 'early_access_feature'
export type ReleaseAllOrder = '-created_at' | 'created_at'
export const RELEASE_ALL_TYPES: ReleaseAllType[] = ['release', 'feature_flag', 'experiment', 'early_access_feature']

export interface ReleaseAllOwner {
    id: number
    uuid: string
    first_name?: string
    last_name?: string
    email: string
}

export type ReleaseAllTone = 'default' | 'info' | 'success' | 'warning'

export interface ReleaseAllRow {
    key: string
    type: ReleaseAllType
    id: string
    name: string
    status: string
    tone: ReleaseAllTone
    stage?: ReleaseRow['stage']
    createdAt: string
    href: string
    owner: ReleaseAllOwner | null
}

export interface ReleaseAllFilters {
    search: string
    types: ReleaseAllType[]
    owners: number[]
    order: ReleaseAllOrder
}

export type ReleaseAllListState = 'loading' | 'error' | 'no-matches' | 'empty' | 'ready'

interface SourcePage {
    rows: ReleaseAllRow[]
    hasMore: boolean
    tail: string | null
    cursor?: string | null
}

interface SourceState {
    rows: ReleaseAllRow[]
    tail: string | null
    offset: number
    cursor: string | null
    hasMore: boolean
    loading: boolean
    failed: boolean
}

type Sources = Record<ReleaseAllType, SourceState>

export const DEFAULT_FILTERS: ReleaseAllFilters = { search: '', types: [], owners: [], order: '-created_at' }
const EMPTY_SOURCE: SourceState = {
    rows: [],
    tail: null,
    offset: 0,
    cursor: null,
    hasMore: true,
    loading: false,
    failed: false,
}

function emptySources(): Sources {
    return Object.fromEntries(RELEASE_ALL_TYPES.map((type) => [type, EMPTY_SOURCE])) as Sources
}

const EXPERIMENT_TONE: Record<string, ReleaseAllTone> = {
    running: 'success',
    paused: 'warning',
    exposure_frozen: 'info',
}

const EARLY_ACCESS_TONE: Record<string, ReleaseAllTone> = {
    alpha: 'info',
    beta: 'warning',
    'general-availability': 'success',
}

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1).replace(/[-_]/g, ' ')
}

function ownerOf(user: ReleaseAllOwner | null | undefined): ReleaseAllOwner | null {
    return user
        ? { id: user.id, uuid: user.uuid, first_name: user.first_name, last_name: user.last_name, email: user.email }
        : null
}

function isType(value: string): value is ReleaseAllType {
    return (RELEASE_ALL_TYPES as string[]).includes(value)
}

function listParam(value: unknown): string[] {
    if (Array.isArray(value)) {
        return value.map(String)
    }
    return typeof value === 'string' || typeof value === 'number' ? String(value).split(',').filter(Boolean) : []
}

export function filtersFromSearchParams(params: Record<string, unknown>): ReleaseAllFilters {
    return {
        search: typeof params.search === 'string' ? params.search.trim() : '',
        types: listParam(params.type).filter(isType),
        owners: listParam(params.owner)
            .map(Number)
            .filter((id) => Number.isInteger(id) && id > 0),
        order: params.order === 'created_at' ? 'created_at' : '-created_at',
    }
}

export function searchParamsOfFilters(filters: ReleaseAllFilters): Record<string, string> {
    return Object.fromEntries(
        Object.entries({
            search: filters.search,
            type: filters.types.join(','),
            owner: filters.owners.join(','),
            order: filters.order === DEFAULT_FILTERS.order ? '' : filters.order,
        }).filter(([, value]) => value)
    )
}

function sameFilters(a: ReleaseAllFilters, b: ReleaseAllFilters): boolean {
    return JSON.stringify(searchParamsOfFilters(a)) === JSON.stringify(searchParamsOfFilters(b))
}

function newestFirst(filters: ReleaseAllFilters): boolean {
    return filters.order === '-created_at'
}

async function fetchPage(
    type: ReleaseAllType,
    projectId: string,
    filters: ReleaseAllFilters,
    { offset, cursor }: SourceState
): Promise<SourcePage> {
    const search = filters.search || undefined
    const owners = filters.owners.length ? filters.owners.join(',') : undefined
    if (type === 'release') {
        const page = await releasesCatalogReleasesRetrieve(projectId, {
            search,
            owner: owners,
            order: filters.order,
            limit: ALL_PAGE_SIZE,
            cursor: cursor ?? undefined,
        })
        return {
            hasMore: !!page.next_cursor,
            cursor: page.next_cursor,
            tail: page.results.at(-1)?.created_at ?? null,
            rows: page.results.map((release) => ({
                key: `release-${release.id}`,
                type,
                id: release.id,
                name: release.name,
                status: '',
                tone: 'default',
                createdAt: release.created_at,
                href: urls.release(release.id),
                owner: ownerOf(release.owner),
            })),
        }
    }
    if (type === 'feature_flag') {
        const page = await releasesCatalogFlagsRetrieve(projectId, {
            search,
            created_by: owners,
            order: filters.order,
            limit: ALL_PAGE_SIZE,
            offset,
        })
        return {
            hasMore: page.has_more,
            tail: page.results.at(-1)?.created_at ?? null,
            rows: page.results.map((flag) => ({
                key: `flag-${flag.id}`,
                type,
                id: String(flag.id),
                name: flag.key,
                status: flag.active ? 'Active' : 'Disabled',
                tone: flag.active ? 'success' : 'default',
                createdAt: flag.created_at,
                href: urls.featureFlag(flag.id),
                owner: ownerOf(flag.created_by),
            })),
        }
    }
    if (type === 'experiment') {
        const page = await experimentsList(projectId, {
            search,
            created_by_id: owners,
            order: filters.order,
            limit: ALL_PAGE_SIZE,
            offset,
        })
        return {
            hasMore: !!page.next,
            tail: page.results.at(-1)?.created_at ?? null,
            rows: page.results.map((experiment) => ({
                key: `experiment-${experiment.id}`,
                type,
                id: String(experiment.id),
                name: experiment.name,
                status: capitalize(experiment.status ?? 'draft'),
                tone: EXPERIMENT_TONE[experiment.status ?? ''] ?? 'default',
                createdAt: experiment.created_at ?? '',
                href: urls.experiment(experiment.id as number),
                owner: ownerOf(experiment.created_by),
            })),
        }
    }
    const page = await earlyAccessFeatureList(projectId, {
        search,
        created_by_id: owners,
        order: filters.order,
        limit: ALL_PAGE_SIZE,
        offset,
    })
    return {
        hasMore: !!page.next,
        tail: page.results.at(-1)?.created_at ?? null,
        rows: page.results.map((item) => ({
            key: `ea-${item.id}`,
            type,
            id: item.id,
            name: item.name,
            status: capitalize(item.stage),
            tone: EARLY_ACCESS_TONE[item.stage] ?? 'default',
            createdAt: item.created_at ?? '',
            href: urls.earlyAccessFeature(item.id),
            owner: ownerOf(item.created_by),
        })),
    }
}

let requestGeneration = 0

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface releaseAllLogicValues {
    currentProjectId: number | null // projectLogic
    releasesAreaEnabled: boolean // releaseLogic
    releasesEnabled: boolean // releaseLogic
    rows: ReleaseRow[] // releaseLogic
    activeTypes: ReleaseAllType[]
    availableTypes: ReleaseAllType[]
    cutoff: string | null
    displayRows: ReleaseAllRow[]
    failedTypes: ReleaseAllType[]
    filters: ReleaseAllFilters
    firstLoad: boolean
    hasMore: boolean
    keptRows: ReleaseAllRow[]
    listState: ReleaseAllListState
    loading: boolean
    narrowingFiltersActive: boolean
    searchInput: string
    sources: Sources
    stageById: Map<string, ReleaseRow['stage']>
    stale: boolean
    visibleRows: ReleaseAllRow[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface releaseAllLogicActions {
    setFeatureFlags: (
        flags: string[],
        variants: Record<string, boolean | string>
    ) => {
        flags: string[]
        variants: Record<string, boolean | string>
    } // featureFlagLogic
    markAutoImported: (projectId: string) => {
        projectId: string
    } // releaseImportLogic
    applyFilters: (filters: ReleaseAllFilters) => {
        filters: ReleaseAllFilters
    }
    clearFilters: () => {
        value: true
    }
    clearNarrowingFilters: () => {
        value: true
    }
    itemOpened: (
        row: ReleaseAllRow,
        position: number
    ) => {
        position: number
        row: ReleaseAllRow
    }
    keepRows: (rows: ReleaseAllRow[]) => {
        rows: ReleaseAllRow[]
    }
    loadMore: () => {
        value: true
    }
    loadSource: (type: ReleaseAllType) => {
        type: ReleaseAllType
    }
    retry: () => {
        value: true
    }
    setFilters: (filters: Partial<ReleaseAllFilters>) => {
        filters: Partial<ReleaseAllFilters>
    }
    setSearchInput: (search: string) => {
        search: string
    }
    sourceFailed: (type: ReleaseAllType) => {
        type: ReleaseAllType
    }
    sourceLoaded: (
        type: ReleaseAllType,
        page: SourcePage
    ) => {
        page: SourcePage
        type: ReleaseAllType
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface releaseAllLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        availableTypes: (releasesEnabled: boolean) => ReleaseAllType[]
        activeTypes: (filters: ReleaseAllFilters, availableTypes: ReleaseAllType[]) => ReleaseAllType[]
        cutoff: (sources: Sources, activeTypes: ReleaseAllType[], filters: ReleaseAllFilters) => string | null
        stageById: (rows: ReleaseRow[]) => Map<string, ReleaseRow['stage']>
        visibleRows: (
            sources: Sources,
            activeTypes: ReleaseAllType[],
            stageById: Map<string, import('./releaseUtils').ReleaseStage>,
            cutoff: string | null,
            filters: ReleaseAllFilters
        ) => ReleaseAllRow[]
        hasMore: (sources: Sources, activeTypes: ReleaseAllType[]) => boolean
        loading: (sources: Sources, activeTypes: ReleaseAllType[]) => boolean
        firstLoad: (sources: Sources, activeTypes: ReleaseAllType[]) => boolean
        failedTypes: (sources: Sources, activeTypes: ReleaseAllType[]) => ReleaseAllType[]
        displayRows: (
            firstLoad: boolean,
            keptRows: ReleaseAllRow[],
            visibleRows: ReleaseAllRow[],
            availableTypes: ReleaseAllType[]
        ) => ReleaseAllRow[]
        stale: (firstLoad: boolean, keptRows: ReleaseAllRow[]) => boolean
        narrowingFiltersActive: (filters: ReleaseAllFilters) => boolean
        listState: (
            displayRows: ReleaseAllRow[],
            firstLoad: boolean,
            hasMore: boolean,
            failedTypes: ReleaseAllType[],
            filters: ReleaseAllFilters
        ) => ReleaseAllListState
    }
}

export type releaseAllLogicType = MakeLogicType<
    releaseAllLogicValues,
    releaseAllLogicActions,
    Record<string, any>,
    releaseAllLogicMeta
>

export const releaseAllLogic = kea<releaseAllLogicType>([
    path(['products', 'release', 'frontend', 'releaseAllLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], releaseLogic, ['rows', 'releasesEnabled', 'releasesAreaEnabled']],
        actions: [releaseImportLogic, ['markAutoImported'], featureFlagLogic, ['setFeatureFlags']],
    })),
    actions({
        setFilters: (filters: Partial<ReleaseAllFilters>) => ({ filters }),
        applyFilters: (filters: ReleaseAllFilters) => ({ filters }),
        setSearchInput: (search: string) => ({ search }),
        clearFilters: true,
        clearNarrowingFilters: true,
        loadMore: true,
        retry: true,
        keepRows: (rows: ReleaseAllRow[]) => ({ rows }),
        loadSource: (type: ReleaseAllType) => ({ type }),
        sourceLoaded: (type: ReleaseAllType, page: SourcePage) => ({ type, page }),
        sourceFailed: (type: ReleaseAllType) => ({ type }),
        itemOpened: (row: ReleaseAllRow, position: number) => ({ row, position }),
    }),
    reducers({
        filters: [DEFAULT_FILTERS, { applyFilters: (_, { filters }) => filters }],
        searchInput: [
            '',
            {
                setSearchInput: (_, { search }) => search,
                applyFilters: (state, { filters }) => (state.trim() === filters.search ? state : filters.search),
            },
        ],
        keptRows: [[] as ReleaseAllRow[], { keepRows: (_, { rows }) => rows }],
        sources: [
            emptySources(),
            {
                applyFilters: () => emptySources(),
                markAutoImported: () => emptySources(),
                loadSource: (state, { type }) => ({
                    ...state,
                    [type]: { ...state[type], loading: true, failed: false },
                }),
                sourceLoaded: (state, { type, page }) => ({
                    ...state,
                    [type]: {
                        rows: [...state[type].rows, ...page.rows],
                        tail: page.tail ?? state[type].tail,
                        offset: state[type].offset + ALL_PAGE_SIZE,
                        cursor: page.cursor ?? null,
                        hasMore: page.hasMore,
                        loading: false,
                        failed: false,
                    },
                }),
                sourceFailed: (state, { type }) => ({
                    ...state,
                    [type]: { ...state[type], hasMore: false, loading: false, failed: true },
                }),
                retry: (state) =>
                    Object.fromEntries(
                        Object.entries(state).map(([type, source]) => [
                            type,
                            source.failed ? { ...source, hasMore: true, failed: false } : { ...source, loading: false },
                        ])
                    ) as Sources,
            },
        ],
    }),
    selectors({
        availableTypes: [
            (s) => [s.releasesEnabled],
            (releasesEnabled: boolean): ReleaseAllType[] =>
                RELEASE_ALL_TYPES.filter((type) => type !== 'release' || releasesEnabled),
        ],
        activeTypes: [
            (s) => [s.filters, s.availableTypes],
            (filters: ReleaseAllFilters, availableTypes: ReleaseAllType[]): ReleaseAllType[] => {
                const selected = filters.types.filter((type) => availableTypes.includes(type))
                return selected.length ? selected : availableTypes
            },
        ],
        cutoff: [
            (s) => [s.sources, s.activeTypes, s.filters],
            (sources: Sources, activeTypes: ReleaseAllType[], filters: ReleaseAllFilters): string | null => {
                const tails = activeTypes
                    .filter((type) => sources[type].hasMore && sources[type].tail)
                    .map((type) => sources[type].tail as string)
                if (!tails.length) {
                    return null
                }
                const descending = newestFirst(filters)
                return tails.reduce((edge, tail) => ((descending ? tail > edge : tail < edge) ? tail : edge))
            },
        ],
        stageById: [
            (s) => [s.rows],
            (rows: ReleaseRow[]): Map<string, ReleaseRow['stage']> => new Map(rows.map((row) => [row.id, row.stage])),
        ],
        visibleRows: [
            (s) => [s.sources, s.activeTypes, s.stageById, s.cutoff, s.filters],
            (
                sources: Sources,
                activeTypes: ReleaseAllType[],
                stageById: Map<string, ReleaseRow['stage']>,
                cutoff: string | null,
                filters: ReleaseAllFilters
            ): ReleaseAllRow[] => {
                const descending = newestFirst(filters)
                return activeTypes
                    .flatMap((type) => sources[type].rows)
                    .filter((row) => !cutoff || (descending ? row.createdAt >= cutoff : row.createdAt <= cutoff))
                    .sort((a, b) =>
                        descending ? b.createdAt.localeCompare(a.createdAt) : a.createdAt.localeCompare(b.createdAt)
                    )
                    .map((row) => {
                        const stage = row.type === 'release' ? stageById.get(row.id) : undefined
                        return stage ? { ...row, status: STAGE_LABEL[stage], stage } : row
                    })
            },
        ],
        hasMore: [
            (s) => [s.sources, s.activeTypes],
            (sources: Sources, activeTypes: ReleaseAllType[]): boolean =>
                activeTypes.some((type) => sources[type].hasMore),
        ],
        loading: [
            (s) => [s.sources, s.activeTypes],
            (sources: Sources, activeTypes: ReleaseAllType[]): boolean =>
                activeTypes.some((type) => sources[type].loading),
        ],
        firstLoad: [
            (s) => [s.sources, s.activeTypes],
            (sources: Sources, activeTypes: ReleaseAllType[]): boolean =>
                activeTypes.some((type) => sources[type].offset === 0 && !sources[type].failed),
        ],
        failedTypes: [
            (s) => [s.sources, s.activeTypes],
            (sources: Sources, activeTypes: ReleaseAllType[]): ReleaseAllType[] =>
                activeTypes.filter((type) => sources[type].failed),
        ],
        displayRows: [
            (s) => [s.firstLoad, s.keptRows, s.visibleRows, s.availableTypes],
            (
                firstLoad: boolean,
                keptRows: ReleaseAllRow[],
                visibleRows: ReleaseAllRow[],
                availableTypes: ReleaseAllType[]
            ): ReleaseAllRow[] =>
                (firstLoad ? keptRows : visibleRows).filter((row) => availableTypes.includes(row.type)),
        ],
        stale: [
            (s) => [s.firstLoad, s.keptRows],
            (firstLoad: boolean, keptRows: ReleaseAllRow[]): boolean => firstLoad && keptRows.length > 0,
        ],
        narrowingFiltersActive: [
            (s) => [s.filters],
            (filters: ReleaseAllFilters): boolean => filters.types.length > 0 || filters.owners.length > 0,
        ],
        listState: [
            (s) => [s.displayRows, s.firstLoad, s.hasMore, s.failedTypes, s.filters],
            (
                displayRows: ReleaseAllRow[],
                firstLoad: boolean,
                hasMore: boolean,
                failedTypes: ReleaseAllType[],
                filters: ReleaseAllFilters
            ): ReleaseAllListState => {
                if (displayRows.length) {
                    return 'ready'
                }
                if (firstLoad || hasMore) {
                    return 'loading'
                }
                if (failedTypes.length) {
                    return 'error'
                }
                return filters.search || filters.types.length || filters.owners.length ? 'no-matches' : 'empty'
            },
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        setFeatureFlags: () => {
            if (
                cache.releasesEnabled !== values.releasesEnabled ||
                cache.releasesAreaEnabled !== values.releasesAreaEnabled
            ) {
                cache.releasesEnabled = values.releasesEnabled
                cache.releasesAreaEnabled = values.releasesAreaEnabled
                actions.keepRows([])
                actions.applyFilters({
                    ...values.filters,
                    types: values.filters.types.filter((type) => values.availableTypes.includes(type)),
                })
            }
        },
        setSearchInput: async ({ search }, breakpoint) => {
            await breakpoint(SEARCH_DEBOUNCE_MS)
            if (search.trim() !== values.filters.search) {
                actions.setFilters({ search: search.trim() })
            }
        },
        setFilters: ({ filters }) => {
            const next = { ...values.filters, ...filters }
            next.types = next.types.filter((type) => values.availableTypes.includes(type))
            if (sameFilters(next, values.filters)) {
                return
            }
            const sameOrderAndOwners = next.order === values.filters.order && next.owners === values.filters.owners
            const kept = values.displayRows.filter(
                (row) => sameOrderAndOwners && (!next.types.length || next.types.includes(row.type))
            )
            actions.keepRows(kept.length ? kept : values.displayRows)
            actions.applyFilters(next)
            if (filters.search) {
                // pinned: analytics event name and properties. Renaming them breaks dashboards.
                posthog.capture('release view all searched', { filter: next.types.join(',') || 'all' })
            }
            if (filters.types || filters.owners || filters.order) {
                // pinned: analytics event name. Renaming it breaks dashboards.
                posthog.capture('release view all filtered', {
                    filter: next.types.join(',') || 'all',
                    owners: next.owners.length,
                    order: next.order,
                })
            }
        },
        applyFilters: () => {
            requestGeneration++
            actions.loadMore()
        },
        clearFilters: () => actions.setFilters({ search: '', types: [], owners: [] }),
        clearNarrowingFilters: () => actions.setFilters({ types: [], owners: [] }),
        markAutoImported: () => {
            requestGeneration++
            actions.loadMore()
        },
        retry: () => {
            requestGeneration++
            actions.loadMore()
        },
        loadMore: () => {
            if (!values.releasesAreaEnabled) {
                return
            }
            const descending = newestFirst(values.filters)
            for (const type of values.activeTypes) {
                const source = values.sources[type]
                const behind =
                    !source.tail ||
                    values.cutoff === null ||
                    (descending ? source.tail >= values.cutoff : source.tail <= values.cutoff)
                if (source.hasMore && !source.loading && behind) {
                    actions.loadSource(type)
                }
            }
        },
        loadSource: async ({ type }) => {
            if (!values.releasesAreaEnabled || !values.activeTypes.includes(type)) {
                return
            }
            const generation = requestGeneration
            try {
                const page = await fetchPage(
                    type,
                    String(values.currentProjectId),
                    values.filters,
                    values.sources[type]
                )
                if (generation === requestGeneration) {
                    actions.sourceLoaded(type, page)
                }
            } catch {
                if (generation === requestGeneration) {
                    actions.sourceFailed(type)
                }
            }
        },
        sourceLoaded: () => {
            if (!values.firstLoad && values.keptRows.length) {
                actions.keepRows([])
            }
        },
        itemOpened: ({ row, position }) => {
            // pinned: analytics event name and properties. Renaming them breaks dashboards.
            posthog.capture('release view all item opened', { object_type: row.type, position })
        },
    })),
    actionToUrl(({ values }) => ({
        applyFilters: () =>
            router.values.location.pathname.endsWith(urls.releases())
                ? [urls.releases(), searchParamsOfFilters(values.filters), router.values.hashParams, { replace: true }]
                : undefined,
    })),
    urlToAction(({ actions, values }) => ({
        [urls.releases()]: (_, searchParams) => {
            const next = filtersFromSearchParams(searchParams)
            next.types = next.types.filter((type) => values.availableTypes.includes(type))
            if (!sameFilters(next, values.filters)) {
                actions.keepRows([])
                actions.applyFilters(next)
            }
        },
    })),
    afterMount(({ actions, values, cache }) => {
        cache.releasesEnabled = values.releasesEnabled
        cache.releasesAreaEnabled = values.releasesAreaEnabled
        actions.loadMore()
    }),
    beforeUnmount(() => {
        requestGeneration++
    }),
])
