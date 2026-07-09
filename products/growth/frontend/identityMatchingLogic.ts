import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { identityMatchingLinksList, identityMatchingLinksRunsRetrieve } from './generated/api'
import type {
    IdentityMatchingLinkApi,
    IdentityMatchingLinksListParams,
    IdentityMatchingLinksListTier,
    IdentityMatchingLinksResponseApi,
    IdentityMatchingRunApi,
    IdentityMatchingRunsResponseApi,
} from './generated/api.schemas'
import type { identityMatchingLogicType } from './identityMatchingLogicType'

export interface IdentityMatchingFilters {
    jobId: string | null
    modelVersion: string | null
    tier: IdentityMatchingLinksListTier | null
    minScore: number | null
    search: string
}

const DEFAULT_FILTERS: IdentityMatchingFilters = {
    jobId: null,
    modelVersion: null,
    tier: null,
    minScore: null,
    search: '',
}

export const LINKS_PAGE_SIZE = 50

export type IdentityMatchingTab = 'links' | 'paid_attribution' | 'runs'

export const identityMatchingLogic = kea<identityMatchingLogicType>([
    path(['products', 'growth', 'frontend', 'identityMatchingLogic']),
    actions({
        setFilters: (filters: Partial<IdentityMatchingFilters>) => ({ filters }),
        setPage: (page: number) => ({ page }),
        setActiveTab: (tab: IdentityMatchingTab) => ({ tab }),
    }),
    loaders(({ values, cache }) => ({
        runsResponse: {
            __default: null as IdentityMatchingRunsResponseApi | null,
            loadRuns: async () => {
                const projectId = String(teamLogic.values.currentTeamId)
                return await identityMatchingLinksRunsRetrieve(projectId)
            },
        },
        linksResponse: {
            __default: null as IdentityMatchingLinksResponseApi | null,
            loadLinks: async (_: unknown, breakpoint) => {
                await breakpoint(300)
                const projectId = String(teamLogic.values.currentTeamId)
                const { jobId, modelVersion, tier, minScore, search } = values.filters
                const offset = (values.page - 1) * LINKS_PAGE_SIZE
                const params: IdentityMatchingLinksListParams = { limit: LINKS_PAGE_SIZE, offset }
                if (jobId) {
                    params.job_id = jobId
                }
                if (modelVersion) {
                    params.model_version = modelVersion
                }
                if (tier) {
                    params.tier = tier
                }
                if (minScore !== null) {
                    params.min_score = minScore
                }
                if (search.trim()) {
                    params.search = search.trim()
                }
                const requestId = (cache.loadLinksSeq = (cache.loadLinksSeq ?? 0) + 1)
                const response = await identityMatchingLinksList(projectId, params)
                breakpoint()
                if (requestId !== cache.loadLinksSeq) {
                    return values.linksResponse
                }
                return response
            },
        },
    })),
    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        page: [
            1,
            {
                setPage: (_, { page }) => page,
                setFilters: () => 1,
            },
        ],
        activeTab: [
            'links' as IdentityMatchingTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        links: [(s) => [s.linksResponse], (linksResponse): IdentityMatchingLinkApi[] => linksResponse?.results ?? []],
        linksCount: [(s) => [s.linksResponse], (linksResponse): number => linksResponse?.count ?? 0],
        runs: [(s) => [s.runsResponse], (runsResponse): IdentityMatchingRunApi[] => runsResponse?.results ?? []],
        modelVersions: [
            (s) => [s.runs],
            (runs): string[] => {
                const versions = new Set<string>()
                for (const run of runs) {
                    for (const model of run.models) {
                        versions.add(model.model_version)
                    }
                }
                return Array.from(versions).sort()
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'IdentityMatching',
                    name: 'Identity matching',
                    path: urls.identityMatching(),
                    iconType: 'persons',
                },
            ],
        ],
    }),
    listeners(({ actions }) => ({
        setFilters: () => {
            actions.loadLinks(null)
        },
        setPage: () => {
            actions.loadLinks(null)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRuns()
        actions.loadLinks(null)
    }),
])
