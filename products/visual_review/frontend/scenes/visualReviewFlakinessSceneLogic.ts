import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import type { FlakinessPreset } from '../components/FlakinessStatRow'
import type { FacetBucket, FacetGroups, FacetSelection } from '../components/SnapshotFacetSidebar'
import {
    visualReviewReposFlakinessRetrieve,
    visualReviewReposQuarantineCreate,
    visualReviewReposQuarantineExpireCreate,
} from '../generated/api'
import type { FlakinessEntryApi, FlakinessOverviewApi, RepoApi } from '../generated/api.schemas'
import { parseArea, runTypeLabel } from '../lib/parseIdentifier'
import { visualReviewRepoLogic } from './visualReviewRepoLogic'

export interface VisualReviewFlakinessSceneLogicProps {
    repoId: string
}

// "Most variants" ranks by severity, "most recent" by urgency. A snapshot with
// forty variants last seen three weeks ago and one with eight seen today are
// both worth attention, and neither order answers for the other.
export type FlakinessSort = 'variants' | 'recent'

export type Filters = {
    preset: FlakinessPreset
    typeKeys: string[]
    areas: string[]
    search: string
    sort: FlakinessSort
}

// Unstable is the landing slice: it is the only one that means something is
// wrong right now.
const EMPTY_FILTERS: Filters = {
    preset: 'unstable',
    typeKeys: [],
    areas: [],
    search: '',
    sort: 'variants',
}

// Collapses run_type + browser into one facet key, matching how the snapshots
// overview buckets the same two seed conventions: `run_type=playwright` with
// the browser in metadata, or `run_type=playwright-<browser>` in the column.
function typeKeyOf(entry: FlakinessEntryApi): string {
    const runType = entry.run_type.toLowerCase()
    if (runType === 'playwright' && entry.browser) {
        return `playwright::${entry.browser}`
    }
    if (runType.startsWith('playwright-')) {
        return `playwright::${runType.slice('playwright-'.length)}`
    }
    return entry.run_type
}

function typeLabelOf(key: string): string {
    if (key.startsWith('playwright::')) {
        return runTypeLabel('playwright', key.slice('playwright::'.length))
    }
    return key
}

function matchesPreset(entry: DecoratedEntry, preset: FlakinessPreset): boolean {
    switch (preset) {
        case 'unstable':
            return entry.flakiness_state === 'unstable'
        case 'settled':
            return entry.flakiness_state === 'settled'
        case 'quarantined':
            return entry.is_quarantined
        case 'needs_decision':
            return entry.needs_decision
    }
}

function bucketize(values: string[], labelOf: (value: string) => string = (value) => value): FacetBucket[] {
    const counts = new Map<string, number>()
    for (const value of values) {
        counts.set(value, (counts.get(value) ?? 0) + 1)
    }
    return [...counts.entries()]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .map(([value, count]) => ({ value, count, label: labelOf(value) }))
}

// Area and type key are parsed once per entry so filtering does not re-derive
// them on every keystroke. Exported so kea-typegen can resolve the shape.
export type DecoratedEntry = FlakinessEntryApi & {
    _area: string
    _typeKey: string
}

type FilterDimension = keyof Filters

// One place for the filter rules. `filteredEntries` calls it with nothing
// excluded; `facetGroups` calls it once per dimension with that dimension
// excluded, so a facet's own rows do not zero each other out.
function applyFilters(
    entries: readonly DecoratedEntry[],
    filters: Filters,
    exclude?: FilterDimension
): DecoratedEntry[] {
    const search = filters.search.trim().toLowerCase()
    return entries.filter((entry) => {
        if (exclude !== 'preset' && !matchesPreset(entry, filters.preset)) {
            return false
        }
        if (exclude !== 'typeKeys' && filters.typeKeys.length && !filters.typeKeys.includes(entry._typeKey)) {
            return false
        }
        if (exclude !== 'areas' && filters.areas.length && !filters.areas.includes(entry._area)) {
            return false
        }
        if (exclude !== 'search' && search && !entry.identifier.toLowerCase().includes(search)) {
            return false
        }
        return true
    })
}

function recencyOf(entry: DecoratedEntry): number {
    return entry.last_flaked_at ? new Date(entry.last_flaked_at).getTime() : 0
}

function variantCountOf(entry: DecoratedEntry): number {
    return entry.variant_count
}

// The multi-select filters only expose a toggle, so restoring one from the URL
// means toggling the symmetric difference against what is selected now.
function syncToggles(next: string[], current: string[], toggle: (value: string) => void): void {
    for (const value of next) {
        if (!current.includes(value)) {
            toggle(value)
        }
    }
    for (const value of current) {
        if (!next.includes(value)) {
            toggle(value)
        }
    }
}

// Both orders fall back to the other measure, then to the name, so the list is
// stable and a tie never reshuffles between renders.
function sortEntries(entries: DecoratedEntry[], sort: FlakinessSort): DecoratedEntry[] {
    const primary = sort === 'recent' ? recencyOf : variantCountOf
    const secondary = sort === 'recent' ? variantCountOf : recencyOf
    return [...entries].sort(
        (a, b) => primary(b) - primary(a) || secondary(b) - secondary(a) || a.identifier.localeCompare(b.identifier)
    )
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface visualReviewFlakinessSceneLogicValues {
    currentProjectId: number | string // teamLogic
    repo: RepoApi | null // visualReviewRepoLogic
    breadcrumbs: Breadcrumb[]
    decoratedEntries: DecoratedEntry[]
    entries: FlakinessEntryApi[]
    facetGroups: FacetGroups
    facetSelection: FacetSelection
    filteredEntries: DecoratedEntry[]
    filters: Filters
    loadError: string | null
    overview: FlakinessOverviewApi | null
    overviewLoading: boolean
    pendingQuarantineKeys: string[]
    repoId: string
    statCounts: Record<FlakinessPreset, number>
    thumbnailBasePath: string | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface visualReviewFlakinessSceneLogicActions {
    clearAllFilters: () => {
        value: true
    }
    loadOverview: () => any
    loadOverviewFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadOverviewSuccess: (
        overview: FlakinessOverviewApi,
        payload?: any
    ) => {
        overview: FlakinessOverviewApi
        payload?: any
    }
    quarantineIdentifier: (
        identifier: string,
        runType: string,
        reason: string,
        expiresAt: string | null,
        sourceRunId: string | null
    ) => {
        expiresAt: string | null
        identifier: string
        reason: string
        runType: string
        sourceRunId: string | null
    }
    quarantineSettled: (
        identifier: string,
        runType: string
    ) => {
        identifier: string
        runType: string
    }
    setPreset: (preset: FlakinessPreset) => {
        preset: FlakinessPreset
    }
    setSearch: (search: string) => {
        search: string
    }
    setSort: (sort: FlakinessSort) => {
        sort: FlakinessSort
    }
    toggleArea: (value: string) => {
        value: string
    }
    toggleType: (value: string) => {
        value: string
    }
    unquarantineIdentifier: (
        identifier: string,
        runType: string
    ) => {
        identifier: string
        runType: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface visualReviewFlakinessSceneLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        repoId: (arg: any) => string
        entries: (overview: FlakinessOverviewApi | null) => FlakinessEntryApi[]
        decoratedEntries: (entries: FlakinessEntryApi[]) => DecoratedEntry[]
        filteredEntries: (decoratedEntries: DecoratedEntry[], filters: Filters) => DecoratedEntry[]
        statCounts: (overview: FlakinessOverviewApi | null) => Record<FlakinessPreset, number>
        facetGroups: (decoratedEntries: DecoratedEntry[], filters: Filters) => FacetGroups
        facetSelection: (filters: Filters) => FacetSelection
        thumbnailBasePath: (currentProjectId: number | string, arg: any) => string | null
        breadcrumbs: (repo: RepoApi | null) => Breadcrumb[]
    }
}

export type visualReviewFlakinessSceneLogicType = MakeLogicType<
    visualReviewFlakinessSceneLogicValues,
    visualReviewFlakinessSceneLogicActions,
    VisualReviewFlakinessSceneLogicProps,
    visualReviewFlakinessSceneLogicMeta
>

export const visualReviewFlakinessSceneLogic = kea<visualReviewFlakinessSceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewFlakinessSceneLogic']),
    props({} as VisualReviewFlakinessSceneLogicProps),
    key((props) => props.repoId),
    connect((props: VisualReviewFlakinessSceneLogicProps) => ({
        values: [teamLogic, ['currentProjectId'], visualReviewRepoLogic({ repoId: props.repoId }), ['repo']],
    })),
    actions({
        setPreset: (preset: FlakinessPreset) => ({ preset }),
        toggleType: (value: string) => ({ value }),
        toggleArea: (value: string) => ({ value }),
        setSearch: (search: string) => ({ search }),
        setSort: (sort: FlakinessSort) => ({ sort }),
        clearAllFilters: true,
        quarantineIdentifier: (
            identifier: string,
            runType: string,
            reason: string,
            expiresAt: string | null,
            sourceRunId: string | null
        ) => ({
            identifier,
            runType,
            reason,
            expiresAt,
            sourceRunId,
        }),
        unquarantineIdentifier: (identifier: string, runType: string) => ({ identifier, runType }),
        quarantineSettled: (identifier: string, runType: string) => ({ identifier, runType }),
    }),
    reducers({
        // The loader resets `overview` to null on failure, which is
        // indistinguishable from an empty repo. Hold the error so the scene can
        // tell "nothing to show" from "we could not look".
        loadError: [
            null as string | null,
            {
                loadOverview: () => null,
                loadOverviewSuccess: () => null,
                loadOverviewFailure: (_state: string | null, { error }: { error: string }) => error || 'Unknown error',
            },
        ],
        pendingQuarantineKeys: [
            [] as string[],
            {
                quarantineIdentifier: (state, { identifier, runType }) => [...state, `${runType}::${identifier}`],
                unquarantineIdentifier: (state, { identifier, runType }) => [...state, `${runType}::${identifier}`],
                // Drop one occurrence, not every match, because the same row can
                // legitimately be in flight twice.
                quarantineSettled: (state, { identifier, runType }) => {
                    const index = state.indexOf(`${runType}::${identifier}`)
                    return index === -1 ? state : [...state.slice(0, index), ...state.slice(index + 1)]
                },
            },
        ],
        filters: [
            EMPTY_FILTERS,
            {
                setPreset: (state, { preset }) => ({ ...state, preset }),
                toggleType: (state, { value }) => ({
                    ...state,
                    typeKeys: state.typeKeys.includes(value)
                        ? state.typeKeys.filter((key) => key !== value)
                        : [...state.typeKeys, value],
                }),
                toggleArea: (state, { value }) => ({
                    ...state,
                    areas: state.areas.includes(value)
                        ? state.areas.filter((area) => area !== value)
                        : [...state.areas, value],
                }),
                setSearch: (state, { search }) => ({ ...state, search }),
                setSort: (state, { sort }) => ({ ...state, sort }),
                clearAllFilters: () => EMPTY_FILTERS,
            },
        ],
    }),
    loaders(({ props, values }) => ({
        overview: [
            null as FlakinessOverviewApi | null,
            {
                loadOverview: async () =>
                    visualReviewReposFlakinessRetrieve(String(values.currentProjectId), props.repoId),
            },
        ],
    })),
    selectors({
        repoId: [() => [(_, p) => p.repoId], (repoId: string): string => repoId],
        entries: [
            (s) => [s.overview],
            (overview: FlakinessOverviewApi | null): FlakinessEntryApi[] => overview?.entries ?? [],
        ],
        decoratedEntries: [
            (s) => [s.entries],
            (entries: FlakinessEntryApi[]): DecoratedEntry[] =>
                entries.map((entry) => ({
                    ...entry,
                    _area: parseArea(entry.identifier),
                    _typeKey: typeKeyOf(entry),
                })),
        ],
        filteredEntries: [
            (s) => [s.decoratedEntries, s.filters],
            (entries: DecoratedEntry[], filters: Filters): DecoratedEntry[] =>
                sortEntries(applyFilters(entries, filters), filters.sort),
        ],
        // Server totals, not counts over `entries`: totals cover the whole
        // population, so the tiles stay right when the payload is capped.
        statCounts: [
            (s) => [s.overview],
            (overview: FlakinessOverviewApi | null): Record<FlakinessPreset, number> => ({
                unstable: overview?.totals.unstable ?? 0,
                settled: overview?.totals.settled ?? 0,
                quarantined: overview?.totals.quarantined ?? 0,
                needs_decision: overview?.totals.needs_decision ?? 0,
            }),
        ],
        facetGroups: [
            (s) => [s.decoratedEntries, s.filters],
            (entries: DecoratedEntry[], filters: Filters): FacetGroups => ({
                type: bucketize(
                    applyFilters(entries, filters, 'typeKeys').map((entry) => entry._typeKey),
                    typeLabelOf
                ),
                area: bucketize(applyFilters(entries, filters, 'areas').map((entry) => entry._area)),
                stability: [],
            }),
        ],
        facetSelection: [
            (s) => [s.filters],
            (filters: Filters): FacetSelection => ({
                type: new Set(filters.typeKeys),
                area: new Set(filters.areas),
                stability: new Set<string>(),
            }),
        ],
        thumbnailBasePath: [
            (s) => [s.currentProjectId, (_, p) => p.repoId],
            (projectId: number | string, repoId: string): string | null =>
                projectId ? `/api/projects/${projectId}/visual_review/repos/${repoId}/thumbnails` : null,
        ],
        // Single scene crumb, matching the runs and snapshots scenes.
        breadcrumbs: [
            (s) => [s.repo],
            (repo: RepoApi | null): Breadcrumb[] => [
                {
                    key: ['visual_review_repo', repo?.id ?? 'unknown'],
                    name: repo?.repo_full_name ?? 'Visual review',
                },
            ],
        ],
    }),
    listeners(({ actions, values, props }) => ({
        quarantineIdentifier: async ({ identifier, runType, reason, expiresAt, sourceRunId }) => {
            try {
                await visualReviewReposQuarantineCreate(String(values.currentProjectId), props.repoId, runType, {
                    identifier,
                    reason,
                    expires_at: expiresAt,
                    // Forward the prior source when extending. The endpoint expires the
                    // old row and creates a replacement, so dropping this loses the link
                    // to the run that prompted the quarantine.
                    source_run_id: sourceRunId,
                })
                lemonToast.success('Quarantined. Runs stop gating on this snapshot.')
            } catch (e: any) {
                lemonToast.error(e?.detail || e?.message || 'Could not quarantine that snapshot. Try again.')
            } finally {
                actions.quarantineSettled(identifier, runType)
                if (!values.pendingQuarantineKeys.length) {
                    actions.loadOverview()
                }
            }
        },
        unquarantineIdentifier: async ({ identifier, runType }) => {
            try {
                await visualReviewReposQuarantineExpireCreate(String(values.currentProjectId), props.repoId, runType, {
                    identifier,
                    reason: '',
                })
                lemonToast.success('Quarantine lifted. Runs gate on this snapshot again.')
            } catch (e: any) {
                lemonToast.error(e?.detail || e?.message || 'Could not lift that quarantine. Try again.')
            } finally {
                actions.quarantineSettled(identifier, runType)
                if (!values.pendingQuarantineKeys.length) {
                    actions.loadOverview()
                }
            }
        },
    })),
    actionToUrl(({ values, props }) => {
        const buildHash = (): Record<string, string> => {
            const filters: Filters = values.filters
            const hash: Record<string, string> = {}
            if (filters.preset !== EMPTY_FILTERS.preset) {
                hash.preset = filters.preset
            }
            if (filters.typeKeys.length) {
                hash.types = filters.typeKeys.join(',')
            }
            if (filters.areas.length) {
                hash.areas = filters.areas.join(',')
            }
            if (filters.search) {
                hash.q = filters.search
            }
            if (filters.sort !== EMPTY_FILTERS.sort) {
                hash.sort = filters.sort
            }
            return hash
        }
        const path = `/visual_review/repos/${props.repoId}/flakiness`
        const toUrl = (): [string, Record<string, string>, Record<string, string>] => [path, {}, buildHash()]
        return {
            setPreset: toUrl,
            toggleType: toUrl,
            toggleArea: toUrl,
            setSearch: toUrl,
            setSort: toUrl,
            clearAllFilters: () => [path, {}, {}],
        }
    }),
    urlToAction(({ actions, values, props }) => ({
        '/visual_review/repos/:repoId/flakiness': (params, _searchParams, hash) => {
            if (params.repoId !== props.repoId) {
                return
            }
            const current: Filters = values.filters
            const next: Filters = {
                preset: (hash.preset as FlakinessPreset) ?? EMPTY_FILTERS.preset,
                typeKeys: hash.types ? hash.types.split(',') : [],
                areas: hash.areas ? hash.areas.split(',') : [],
                search: hash.q ?? '',
                sort: hash.sort === 'recent' ? 'recent' : 'variants',
            }
            if (next.preset !== current.preset) {
                actions.setPreset(next.preset)
            }
            if (next.search !== current.search) {
                actions.setSearch(next.search)
            }
            if (next.sort !== current.sort) {
                actions.setSort(next.sort)
            }
            syncToggles(next.typeKeys, current.typeKeys, actions.toggleType)
            syncToggles(next.areas, current.areas, actions.toggleArea)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadOverview()
    }),
])
