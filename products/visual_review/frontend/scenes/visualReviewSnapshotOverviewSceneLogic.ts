import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'

import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import type { FacetBucket, FacetGroups, FacetSelection } from '../components/SnapshotFacetSidebar'
import type { StatPreset } from '../components/SnapshotStatRow'
import { visualReviewReposBaselinesRetrieve } from '../generated/api'
import type { BaselineEntryApi, BaselineOverviewApi } from '../generated/api.schemas'
import { parseArea, parseTheme, runTypeLabel } from '../lib/parseIdentifier'
import { visualReviewRepoLogic } from './visualReviewRepoLogic'
import type { visualReviewSnapshotOverviewSceneLogicType } from './visualReviewSnapshotOverviewSceneLogicType'

export interface VisualReviewSnapshotOverviewSceneLogicProps {
    repoId: string
}

// We deliberately don't model "show both themes" — for snapshot identifiers
// that ship as light+dark pairs that would double the grid. Picking one side
// dedups by default. Identifiers without a theme suffix are always shown
// regardless of which side is selected.
export type ThemeFilter = 'light' | 'dark'
export type Filters = {
    statPreset: StatPreset
    typeKeys: string[]
    areas: string[]
    stability: string[]
    theme: ThemeFilter
    search: string
}

const EMPTY_FILTERS: Filters = {
    statPreset: 'all',
    typeKeys: [],
    areas: [],
    stability: [],
    theme: 'light',
    search: '',
}

// We collapse run_type + browser into a single "type key" for the facet —
// matches the design's "Storybook 921 / Playwright · chromium 407 / ..." rows.
// Handles two seed conventions in the wild: `run_type=playwright` with browser
// in metadata, or `run_type=playwright-<browser>` baked into the column.
function typeKeyOf(entry: BaselineEntryApi): string {
    const rt = entry.run_type.toLowerCase()
    if (rt === 'playwright' && entry.browser) {
        return `playwright::${entry.browser}`
    }
    if (rt.startsWith('playwright-')) {
        return `playwright::${rt.slice('playwright-'.length)}`
    }
    return entry.run_type
}

function typeLabelOf(key: string): string {
    if (key.startsWith('playwright::')) {
        return runTypeLabel('playwright', key.slice('playwright::'.length))
    }
    return key
}

const STABILITY_KEYS = {
    clean_30d: 'Clean (30d)',
    tolerated_30d: 'Tolerated (30d)',
    quarantined: 'Quarantined',
}

function entryStability(entry: BaselineEntryApi): Array<keyof typeof STABILITY_KEYS> {
    const out: Array<keyof typeof STABILITY_KEYS> = []
    if (entry.is_quarantined) {
        out.push('quarantined')
    }
    if (entry.tolerate_count_30d > 0) {
        out.push('tolerated_30d')
    }
    if (!entry.is_quarantined && entry.tolerate_count_30d === 0) {
        out.push('clean_30d')
    }
    return out
}

function matchesStatPreset(entry: BaselineEntryApi, preset: StatPreset): boolean {
    switch (preset) {
        case 'tolerated_drift':
            return entry.tolerate_count_30d >= 1
        case 'currently_quarantined':
            return entry.is_quarantined
        case 'all':
        default:
            return true
    }
}

function bucketize(values: string[], labelOf: (v: string) => string = (v) => v): FacetBucket[] {
    const counts = new Map<string, number>()
    for (const v of values) {
        counts.set(v, (counts.get(v) ?? 0) + 1)
    }
    return [...counts.entries()]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .map(([value, count]) => ({ value, count, label: labelOf(value) }))
}

// Pre-decorated entry shape — the kea selector annotates this on every entry
// once so subsequent filter passes can compare without re-deriving area/theme/etc.
// Exported so the kea-typegen output can resolve it.
export type DecoratedEntry = BaselineEntryApi & {
    _area: string
    _theme: 'light' | 'dark' | null
    _typeKey: string
    _stability: string[]
}

// Filter dimensions a caller can opt out of, plus the "preset" stat row.
type FilterDimension = keyof Filters | 'preset'

// Single source of truth for filter logic. `filteredEntries` calls this with no
// exclusion (full set narrows down); `facetGroups` calls it once per dimension
// excluding that dimension so its own facet rows don't zero each other out.
// Without this, the same six clauses lived twice and any new dimension had to
// be added in both places (the bug greptile flagged).
function applyFilters(
    entries: readonly DecoratedEntry[],
    filters: Filters,
    exclude?: FilterDimension
): DecoratedEntry[] {
    const search = filters.search.trim().toLowerCase()
    return entries.filter((e) => {
        if (exclude !== 'preset' && !matchesStatPreset(e, filters.statPreset)) {
            return false
        }
        if (exclude !== 'typeKeys' && filters.typeKeys.length && !filters.typeKeys.includes(e._typeKey)) {
            return false
        }
        if (exclude !== 'areas' && filters.areas.length && !filters.areas.includes(e._area)) {
            return false
        }
        if (
            exclude !== 'stability' &&
            filters.stability.length &&
            !filters.stability.some((s) => e._stability.includes(s as keyof typeof STABILITY_KEYS))
        ) {
            return false
        }
        if (exclude !== 'theme' && e._theme !== null && e._theme !== filters.theme) {
            return false
        }
        if (exclude !== 'search' && search && !e.identifier.toLowerCase().includes(search)) {
            return false
        }
        return true
    })
}

export const visualReviewSnapshotOverviewSceneLogic = kea<visualReviewSnapshotOverviewSceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewSnapshotOverviewSceneLogic']),
    props({} as VisualReviewSnapshotOverviewSceneLogicProps),
    key((props) => props.repoId),
    connect((props: VisualReviewSnapshotOverviewSceneLogicProps) => ({
        values: [teamLogic, ['currentProjectId'], visualReviewRepoLogic({ repoId: props.repoId }), ['repo']],
    })),
    actions({
        setStatPreset: (preset: StatPreset) => ({ preset }),
        toggleType: (value: string) => ({ value }),
        toggleArea: (value: string) => ({ value }),
        toggleStability: (value: string) => ({ value }),
        setTheme: (theme: ThemeFilter) => ({ theme }),
        setSearch: (search: string) => ({ search }),
        clearAllFilters: true,
    }),
    reducers({
        filters: [
            EMPTY_FILTERS,
            {
                setStatPreset: (state, { preset }) => ({ ...state, statPreset: preset }),
                toggleType: (state, { value }) => ({
                    ...state,
                    typeKeys: state.typeKeys.includes(value)
                        ? state.typeKeys.filter((v) => v !== value)
                        : [...state.typeKeys, value],
                }),
                toggleArea: (state, { value }) => ({
                    ...state,
                    areas: state.areas.includes(value)
                        ? state.areas.filter((v) => v !== value)
                        : [...state.areas, value],
                }),
                toggleStability: (state, { value }) => ({
                    ...state,
                    stability: state.stability.includes(value)
                        ? state.stability.filter((v) => v !== value)
                        : [...state.stability, value],
                }),
                setTheme: (state, { theme }) => ({ ...state, theme }),
                setSearch: (state, { search }) => ({ ...state, search }),
                clearAllFilters: () => EMPTY_FILTERS,
            },
        ],
    }),
    loaders(({ props, values }) => ({
        overview: [
            null as BaselineOverviewApi | null,
            {
                loadOverview: async () => {
                    return visualReviewReposBaselinesRetrieve(String(values.currentProjectId), props.repoId)
                },
            },
        ],
    })),
    selectors({
        repoId: [() => [(_, p) => p.repoId], (repoId: string): string => repoId],
        entries: [(s) => [s.overview], (overview): BaselineEntryApi[] => overview?.entries ?? []],
        // Pre-compute parsed area + theme + typeKey + stability tags for each
        // entry so subsequent filter passes don't re-derive on every keystroke.
        decoratedEntries: [
            (s) => [s.entries],
            (
                entries
            ): Array<
                BaselineEntryApi & {
                    _area: string
                    _theme: 'light' | 'dark' | null
                    _typeKey: string
                    _stability: string[]
                }
            > =>
                entries.map((e) => ({
                    ...e,
                    _area: parseArea(e.identifier),
                    _theme: parseTheme(e.identifier).theme,
                    _typeKey: typeKeyOf(e),
                    _stability: entryStability(e),
                })),
        ],
        // The sort applied to filteredEntries depends on the active stat
        // preset — alphabetical for the broad "All" view, severity-style
        // ordering for the slices that highlight problems. Keeping it
        // hardcoded per preset (rather than user-pickable) keeps the UX
        // tight; the indicator label in the toolbar tells the user which
        // sort is active.
        sortLabel: [
            (s) => [s.filters],
            (filters): { kind: 'alpha' | 'drift'; label: string } => {
                if (filters.statPreset === 'all') {
                    return { kind: 'alpha', label: 'name (A → Z)' }
                }
                return { kind: 'drift', label: 'drift avg (high → low)' }
            },
        ],
        filteredEntries: [
            (s) => [s.decoratedEntries, s.filters, s.sortLabel],
            (entries, filters, sortLabel) => {
                const filtered = applyFilters(entries, filters)
                if (sortLabel.kind === 'alpha') {
                    filtered.sort((a, b) => a.identifier.localeCompare(b.identifier))
                } else {
                    filtered.sort(
                        (a, b) =>
                            (b.recent_diff_avg ?? 0) - (a.recent_diff_avg ?? 0) ||
                            b.tolerate_count_30d - a.tolerate_count_30d ||
                            a.identifier.localeCompare(b.identifier)
                    )
                }
                return filtered
            },
        ],
        // Trust-debt count surfaced inline on the Tolerated tile. Falls back
        // to recomputing client-side when the server didn't ship totals.
        frequentlyToleratedCount: [
            (s) => [s.decoratedEntries, s.overview],
            (entries, overview): number =>
                overview?.totals.frequently_tolerated ?? entries.filter((e) => e.tolerate_count_90d >= 3).length,
        ],
        statCounts: [
            (s) => [s.decoratedEntries, s.overview],
            (entries, overview): Record<StatPreset, number> => {
                const totals = overview?.totals
                // When the filter set is "neutral" (preset=all) we want the
                // stat row to show the full universe counts even if entries
                // is truncated. Use server totals as the source of truth.
                if (totals) {
                    return {
                        all: totals.all_snapshots,
                        tolerated_drift: totals.recently_tolerated,
                        currently_quarantined: totals.currently_quarantined,
                    }
                }
                return {
                    all: entries.length,
                    tolerated_drift: entries.filter((e) => e.tolerate_count_30d >= 1).length,
                    currently_quarantined: entries.filter((e) => e.is_quarantined).length,
                }
            },
        ],
        // Facet buckets recompute over the filtered set so counts narrow as
        // the user picks more filters — except for the dimension being faceted
        // (otherwise picking a TYPE would zero out every other TYPE bucket).
        facetGroups: [
            (s) => [s.decoratedEntries, s.filters],
            (entries, filters): FacetGroups => {
                const typeBase = applyFilters(entries, filters, 'typeKeys')
                const areaBase = applyFilters(entries, filters, 'areas')
                const stabilityBase = applyFilters(entries, filters, 'stability')
                return {
                    type: bucketize(
                        typeBase.map((e) => e._typeKey),
                        typeLabelOf
                    ),
                    area: bucketize(areaBase.map((e) => e._area)),
                    stability: Object.entries(STABILITY_KEYS).map(([k, label]) => ({
                        value: k,
                        label,
                        count: stabilityBase.filter((e) => e._stability.includes(k as keyof typeof STABILITY_KEYS))
                            .length,
                    })),
                }
            },
        ],
        facetSelection: [
            (s) => [s.filters],
            (filters): FacetSelection => ({
                type: new Set(filters.typeKeys),
                area: new Set(filters.areas),
                stability: new Set(filters.stability),
            }),
        ],
        thumbnailBasePath: [
            (s) => [s.currentProjectId, (_, p) => p.repoId],
            (projectId, repoId): string | null =>
                projectId ? `/api/projects/${projectId}/visual_review/repos/${repoId}/thumbnails` : null,
        ],
        // Single scene crumb — see runs scene for why we collapse to one.
        breadcrumbs: [
            (s) => [s.repo],
            (repo): Breadcrumb[] => [
                {
                    key: ['visual_review_repo', repo?.id ?? 'unknown'],
                    name: repo?.repo_full_name ?? 'Visual review',
                },
            ],
        ],
    }),
    actionToUrl(({ values, props }) => {
        const buildHash = (): Record<string, string> => {
            const f = values.filters
            const out: Record<string, string> = {}
            if (f.statPreset !== 'all') {
                out.preset = f.statPreset
            }
            if (f.typeKeys.length) {
                out.types = f.typeKeys.join(',')
            }
            if (f.areas.length) {
                out.areas = f.areas.join(',')
            }
            if (f.stability.length) {
                out.stability = f.stability.join(',')
            }
            if (f.theme !== EMPTY_FILTERS.theme) {
                out.theme = f.theme
            }
            if (f.search) {
                out.q = f.search
            }
            return out
        }
        const path = `/visual_review/repos/${props.repoId}/snapshots`
        return {
            setStatPreset: () => [path, {}, buildHash()],
            toggleType: () => [path, {}, buildHash()],
            toggleArea: () => [path, {}, buildHash()],
            toggleStability: () => [path, {}, buildHash()],
            setTheme: () => [path, {}, buildHash()],
            setSearch: () => [path, {}, buildHash()],
            clearAllFilters: () => [path, {}, {}],
        }
    }),
    urlToAction(({ actions, values, props }) => ({
        '/visual_review/repos/:repoId/snapshots': (params, _searchParams, hash) => {
            if (params.repoId !== props.repoId) {
                return
            }
            const f = values.filters
            const next: Filters = {
                statPreset: (hash.preset as StatPreset) ?? 'all',
                typeKeys: hash.types ? hash.types.split(',') : [],
                areas: hash.areas ? hash.areas.split(',') : [],
                stability: hash.stability ? hash.stability.split(',') : [],
                theme: hash.theme === 'dark' ? 'dark' : 'light',
                search: hash.q ?? '',
            }
            if (next.statPreset !== f.statPreset) {
                actions.setStatPreset(next.statPreset)
            }
            if (next.search !== f.search) {
                actions.setSearch(next.search)
            }
            if (next.theme !== f.theme) {
                actions.setTheme(next.theme)
            }
            // For multi-selects, only diff if different.
            if (next.typeKeys.join(',') !== f.typeKeys.join(',')) {
                f.typeKeys.forEach((v) => actions.toggleType(v))
                next.typeKeys.forEach((v) => actions.toggleType(v))
            }
            if (next.areas.join(',') !== f.areas.join(',')) {
                f.areas.forEach((v) => actions.toggleArea(v))
                next.areas.forEach((v) => actions.toggleArea(v))
            }
            if (next.stability.join(',') !== f.stability.join(',')) {
                f.stability.forEach((v) => actions.toggleStability(v))
                next.stability.forEach((v) => actions.toggleStability(v))
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadOverview()
    }),
])
