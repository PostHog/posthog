import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { toParams } from 'lib/utils/url'

import {
    featureFlagsStaffCacheClearCreate,
    featureFlagsStaffCacheEntryRetrieve,
    featureFlagsStaffCacheRebuildCreate,
    featureFlagsStaffTeamsList,
} from '../generated/api'
import type {
    CachesEnumApi,
    FeatureFlagsStaffCacheEntryRetrieveCache,
    StaffCacheEntryResponseApi,
    StaffCacheMutationResponseApi,
    StaffCacheTeamStatusApi,
    StaffTeamResultApi,
} from '../generated/api.schemas'
import type { featureFlagsStaffToolsLogicType } from './featureFlagsStaffToolsLogicType'

// What rebuild/clear can act on. Mirrors the backend's CACHE_CHOICES.
export type StaffCacheKind = CachesEnumApi

// What status/entry can read. Mirrors the backend's READABLE_CACHE_CHOICES: unlike mutation,
// the two definitions-cache variants are individually observable even though they're only
// mutated as a pair (see the backend's staff_cache.py module docstring).
export type StaffReadableCacheKind = FeatureFlagsStaffCacheEntryRetrieveCache

export const CACHE_LABELS: Record<StaffReadableCacheKind, string> = {
    evaluation: 'Flags cache',
    definitions: 'Definitions cache (cohorts)',
    definitions_no_cohorts: 'Definitions cache (no cohorts)',
}

const MIN_SEARCH_LENGTH = 2
const SEARCH_DEBOUNCE_MS = 300
const STAFF_CACHE_URL = 'api/feature_flags_staff_cache'

export type StaffTeamResult = StaffTeamResultApi
export type StaffCacheTeamStatus = StaffCacheTeamStatusApi
export type StaffCacheEntryStatus = StaffCacheTeamStatusApi['evaluation']
export type StaffCacheMutationResponse = StaffCacheMutationResponseApi
export type StaffCacheEntry = StaffCacheEntryResponseApi

export const featureFlagsStaffToolsLogic = kea<featureFlagsStaffToolsLogicType>([
    path(['products', 'feature_flags', 'frontend', 'staff', 'featureFlagsStaffToolsLogic']),
    actions({
        setSelectedTeamIds: (teamIds: number[]) => ({ teamIds }),
        seedTeamFromDeepLink: (teamId: number) => ({ teamId }),
        closeCacheEntryModal: true,
    }),
    loaders(({ values }) => ({
        teamSearchResults: [
            [] as StaffTeamResult[],
            {
                searchTeams: async ({ query }: { query: string }, breakpoint) => {
                    const trimmed = query.trim()
                    // Digit-only queries are exact team-id lookups (allowed at one digit so
                    // deep links to low-id teams resolve); other queries need >= 2 chars.
                    const minLength = /^\d+$/.test(trimmed) ? 1 : MIN_SEARCH_LENGTH
                    if (trimmed.length < minLength) {
                        return []
                    }
                    await breakpoint(SEARCH_DEBOUNCE_MS)
                    const response = await featureFlagsStaffTeamsList({ search: query })
                    breakpoint()
                    return response.results
                },
            },
        ],
        cacheStatus: [
            [] as StaffCacheTeamStatus[],
            {
                loadCacheStatus: async (_: void, breakpoint) => {
                    const teamIds = values.selectedTeamIds
                    if (teamIds.length === 0) {
                        return []
                    }
                    // Debounce so selecting several teams in quick succession collapses into one
                    // fetch of the final selection instead of refetching the growing selection on
                    // every single add (matches the searchTeams debounce pattern above).
                    await breakpoint(SEARCH_DEBOUNCE_MS)
                    // team_ids is a repeated-key query param (?team_ids=1&team_ids=2); the generated
                    // client serializes array params as a single comma-joined value, which this
                    // ListField-backed endpoint can't parse.
                    // nosemgrep: prefer-codegen-api
                    const response = await api.get<{ results: StaffCacheTeamStatus[] }>(
                        `${STAFF_CACHE_URL}?${toParams({ team_ids: teamIds }, true)}`
                    )
                    breakpoint()
                    return response.results
                },
            },
        ],
        rebuildResult: [
            null as StaffCacheMutationResponse | null,
            {
                rebuildCache: async ({ caches }: { caches: StaffCacheKind[] }) => {
                    return await featureFlagsStaffCacheRebuildCreate({ team_ids: values.selectedTeamIds, caches })
                },
            },
        ],
        clearResult: [
            null as StaffCacheMutationResponse | null,
            {
                clearCache: async ({ caches }: { caches: StaffCacheKind[] }) => {
                    return await featureFlagsStaffCacheClearCreate({ team_ids: values.selectedTeamIds, caches })
                },
            },
        ],
        cacheEntry: [
            null as StaffCacheEntry | null,
            {
                viewCacheEntry: async ({ teamId, cache }: { teamId: number; cache: StaffReadableCacheKind }) => {
                    return await featureFlagsStaffCacheEntryRetrieve({ team_id: teamId, cache })
                },
            },
        ],
    })),
    reducers({
        selectedTeamIds: [
            [] as number[],
            {
                setSelectedTeamIds: (_, { teamIds }) => teamIds,
                seedTeamFromDeepLink: (state, { teamId }) => (state.includes(teamId) ? state : [...state, teamId]),
            },
        ],
        // Accumulate team display info (name/org/token) from every search so the
        // selected-teams table can render more than a bare id, even for teams no
        // longer in the latest search results.
        knownTeams: [
            {} as Record<number, StaffTeamResult>,
            {
                searchTeamsSuccess: (state, { teamSearchResults }) => ({
                    ...state,
                    ...Object.fromEntries(teamSearchResults.map((team) => [team.id, team])),
                }),
            },
        ],
        // Seeds only once per mount so manually deselecting a deep-linked team doesn't
        // bring it back if urlToAction re-runs later (e.g. browser back/forward).
        hasSeededFromDeepLink: [
            false,
            {
                seedTeamFromDeepLink: () => true,
            },
        ],
        viewingCacheEntry: [
            null as { teamId: number; cache: StaffReadableCacheKind } | null,
            {
                viewCacheEntry: (_, { teamId, cache }) => ({ teamId, cache }),
                closeCacheEntryModal: () => null,
            },
        ],
    }),
    selectors({
        selectedTeams: [
            (s) => [s.selectedTeamIds, s.knownTeams],
            (selectedTeamIds: number[], knownTeams: Record<number, StaffTeamResult>): StaffTeamResult[] =>
                selectedTeamIds.map((id) => knownTeams[id]).filter(Boolean),
        ],
        cacheStatusByTeamId: [
            (s) => [s.cacheStatus],
            (cacheStatus: StaffCacheTeamStatus[]): Record<number, StaffCacheTeamStatus> =>
                Object.fromEntries(cacheStatus.map((status) => [status.team_id, status])),
        ],
    }),
    listeners(({ actions }) => {
        const onMutationSuccess = (
            result: StaffCacheMutationResponse | null,
            doneMessage: string,
            partialLabel: string
        ): void => {
            const notFound = result?.not_found_team_ids ?? []
            if (notFound.length > 0) {
                lemonToast.warning(`${partialLabel}, but some team ids were not found: ${notFound.join(', ')}`)
            } else {
                lemonToast.success(doneMessage)
            }
            actions.loadCacheStatus()
        }

        return {
            setSelectedTeamIds: () => {
                actions.loadCacheStatus()
            },
            seedTeamFromDeepLink: ({ teamId }) => {
                actions.searchTeams({ query: String(teamId) })
                actions.loadCacheStatus()
            },
            rebuildCacheSuccess: ({ rebuildResult }) => {
                onMutationSuccess(
                    rebuildResult,
                    'Flag caches rebuild queued. Re-check status in a few seconds.',
                    'Rebuild queued'
                )
            },
            rebuildCacheFailure: () => {
                lemonToast.error('Failed to queue flag caches rebuild.')
            },
            clearCacheSuccess: ({ clearResult }) => {
                onMutationSuccess(clearResult, 'Cache clear queued. Re-check status in a few seconds.', 'Clear queued')
            },
            clearCacheFailure: () => {
                lemonToast.error('Failed to clear cache.')
            },
            viewCacheEntryFailure: () => {
                lemonToast.error('Failed to load cache entry.')
                actions.closeCacheEntryModal()
            },
        }
    }),
    urlToAction(({ actions, values }) => ({
        '/feature_flags/staff': (_, searchParams) => {
            // Team-admin deep link: seed the selected team and resolve its display info
            // (exact id search hits the endpoint's Q(id=...) branch). Seeds only once per
            // mount so manually deselecting the team doesn't bring it back if this handler
            // re-runs later (e.g. browser back/forward).
            const teamId = searchParams.team_id ? Number(searchParams.team_id) : null
            if (teamId && !values.hasSeededFromDeepLink) {
                actions.seedTeamFromDeepLink(teamId)
            }
        },
    })),
])
