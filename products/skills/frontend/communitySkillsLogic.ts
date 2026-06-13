import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { ApiConfig } from '~/lib/api'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { trackedActionToUrl } from '~/lib/logic/scenes/trackedActionToUrl'
import { objectsEqual } from '~/lib/utils'
import { urls } from '~/scenes/urls'

import {
    communitySkillsInstallCreate,
    communitySkillsList,
    communitySkillsVoteCreate,
} from 'products/ai_observability/frontend/generated/api'
import type {
    CommunitySkillListApi,
    PaginatedCommunitySkillListListApi,
} from 'products/ai_observability/frontend/generated/api.schemas'

import type { communitySkillsLogicType } from './communitySkillsLogicType'

export const COMMUNITY_SKILLS_PER_PAGE = 30

export type CommunitySkillTrustTier = 'official' | 'verified' | 'community'

export interface CommunitySkillFilters {
    page: number
    search: string
    order_by: string
    tag: string
    trust_tier: CommunitySkillTrustTier | ''
}

function cleanFilters(values: Partial<CommunitySkillFilters>): CommunitySkillFilters {
    return {
        page: parseInt(String(values.page)) || 1,
        search: String(values.search || ''),
        order_by: values.order_by || '-install_count',
        tag: String(values.tag || ''),
        trust_tier: (values.trust_tier as CommunitySkillTrustTier) || '',
    }
}

function cleanFilterUrlParams(filters: CommunitySkillFilters): Record<string, unknown> {
    return {
        page: filters.page === 1 ? undefined : filters.page,
        search: filters.search || undefined,
        order_by: filters.order_by === '-install_count' ? undefined : filters.order_by,
        tag: filters.tag || undefined,
        trust_tier: filters.trust_tier || undefined,
    }
}

export type CommunitySkillsLogicProps = Record<string, never>

export const communitySkillsLogic = kea<communitySkillsLogicType>([
    path(['scenes', 'skills', 'communitySkillsLogic']),
    props({} as CommunitySkillsLogicProps),

    actions({
        setFilters: (filters: Partial<CommunitySkillFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadSkills: (debounce: boolean = true) => ({ debounce }),
        installSkill: (slug: string, newName?: string) => ({ slug, newName }),
        installSkillSuccess: (slug: string) => ({ slug }),
        installSkillFailure: (slug: string) => ({ slug }),
        toggleVote: (slug: string) => ({ slug }),
        toggleVoteSuccess: (slug: string, voteResult: { has_voted: boolean; vote_count: number }) => ({
            slug,
            voteResult,
        }),
    }),

    reducers({
        rawFilters: [
            null as Partial<CommunitySkillFilters> | null,
            {
                setFilters: (state, { filters, merge }) =>
                    cleanFilters({
                        ...(merge ? state || {} : {}),
                        ...filters,
                        ...('page' in filters ? {} : { page: 1 }),
                    }),
            },
        ],
        // Optimistic per-slug vote state keyed by slug, merged over the server values for snappy UI.
        voteOverrides: [
            {} as Record<string, { has_voted: boolean; vote_count: number }>,
            {
                toggleVoteSuccess: (state, { slug, voteResult }) => ({ ...state, [slug]: voteResult }),
            },
        ],
        installingSlugs: [
            {} as Record<string, boolean>,
            {
                installSkill: (state, { slug }) => ({ ...state, [slug]: true }),
                installSkillSuccess: (state, { slug }) => ({ ...state, [slug]: false }),
                installSkillFailure: (state, { slug }) => ({ ...state, [slug]: false }),
            },
        ],
    }),

    loaders(({ values }) => ({
        skills: [
            { results: [], count: 0 } as PaginatedCommunitySkillListListApi,
            {
                loadSkills: async ({ debounce }, breakpoint) => {
                    if (debounce && values.skills.results.length > 0) {
                        await breakpoint(300)
                    }
                    const { filters } = values
                    return await communitySkillsList(String(ApiConfig.getCurrentTeamId()), {
                        search: filters.search,
                        order_by: filters.order_by,
                        tag: filters.tag,
                        trust_tier: filters.trust_tier || undefined,
                        offset: Math.max(0, (filters.page - 1) * COMMUNITY_SKILLS_PER_PAGE),
                        limit: COMMUNITY_SKILLS_PER_PAGE,
                    })
                },
            },
        ],
    })),

    selectors({
        filters: [
            (s) => [s.rawFilters],
            (rawFilters: Partial<CommunitySkillFilters> | null): CommunitySkillFilters =>
                cleanFilters(rawFilters || {}),
        ],
        count: [(s) => [s.skills], (skills: PaginatedCommunitySkillListListApi) => skills.count],
        // Server results with optimistic vote overrides applied.
        displaySkills: [
            (s) => [s.skills, s.voteOverrides],
            (
                skills: PaginatedCommunitySkillListListApi,
                voteOverrides: Record<string, { has_voted: boolean; vote_count: number }>
            ): CommunitySkillListApi[] =>
                skills.results.map((skill) => {
                    const override = voteOverrides[skill.slug]
                    return override ? { ...skill, ...override } : skill
                }),
        ],
        pagination: [
            (s) => [s.filters, s.count],
            (filters: CommunitySkillFilters, count: number): PaginationManual => ({
                controlled: true,
                pageSize: COMMUNITY_SKILLS_PER_PAGE,
                currentPage: filters.page,
                entryCount: count,
            }),
        ],
    }),

    listeners(({ actions, asyncActions, values, selectors }) => ({
        setFilters: async ({ debounce }, _, __, previousState) => {
            const oldFilters = selectors.filters(previousState)
            if (!objectsEqual(oldFilters, values.filters)) {
                await asyncActions.loadSkills(debounce)
            }
        },

        installSkill: async ({ slug, newName }) => {
            try {
                await communitySkillsInstallCreate(String(ApiConfig.getCurrentTeamId()), slug, {
                    new_name: newName,
                })
                lemonToast.success(`Installed "${newName || slug}" into your project.`)
                actions.installSkillSuccess(slug)
                router.actions.push(urls.skill(newName || slug))
            } catch (e) {
                console.error('Failed to install community skill', e)
                lemonToast.error('Failed to install skill — a skill with that name may already exist.')
                actions.installSkillFailure(slug)
            }
        },

        toggleVote: async ({ slug }) => {
            try {
                const result = await communitySkillsVoteCreate(String(ApiConfig.getCurrentTeamId()), slug)
                actions.toggleVoteSuccess(slug, result)
            } catch (e) {
                console.error('Failed to vote on community skill', e)
                lemonToast.error('Failed to register your vote')
            }
        },
    })),

    trackedActionToUrl(({ values }) => {
        const changeUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] | void => {
            const nextValues = cleanFilterUrlParams(values.filters)
            const urlValues = cleanFilters(router.values.searchParams)
            if (!objectsEqual(values.filters, urlValues)) {
                return [urls.communitySkills(), nextValues, {}, { replace: true }]
            }
        }
        return { setFilters: changeUrl }
    }),

    urlToAction(({ actions, values }) => ({
        [urls.communitySkills()]: (_, searchParams) => {
            const newFilters = cleanFilters(searchParams)
            if (!objectsEqual(values.filters, newFilters)) {
                actions.setFilters(newFilters, false)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadSkills()
    }),
])
