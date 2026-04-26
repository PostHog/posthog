import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { ApiConfig } from '~/lib/api'
import { Sorting } from '~/lib/lemon-ui/LemonTable'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { tabAwareActionToUrl } from '~/lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from '~/lib/logic/scenes/tabAwareUrlToAction'
import { objectsEqual } from '~/lib/utils'
import { sceneLogic } from '~/scenes/sceneLogic'
import { urls } from '~/scenes/urls'

import { llmSkillsList, llmSkillsNameArchiveCreate, llmSkillsNameDuplicateCreate } from '../generated/api'
import type { PaginatedLLMSkillListListApi } from '../generated/api.schemas'
import { cleanPagedSearchOrderParams } from '../utils'
import type { llmSkillsLogicType } from './llmSkillsLogicType'

export const SKILLS_PER_PAGE = 30
export const LLM_SKILLS_FORCE_RELOAD_PARAM = 'llm_skills_force_reload'

export interface SkillFilters {
    page: number
    search: string
    order_by: string
    created_by_id?: number
}

function cleanFilters(values: Partial<SkillFilters>): SkillFilters {
    return {
        page: parseInt(String(values.page)) || 1,
        search: String(values.search || ''),
        order_by: values.order_by || '-created_at',
        created_by_id: values.created_by_id ? Number(values.created_by_id) : undefined,
    }
}

export interface LLMSkillsLogicProps {
    tabId?: string
}

export const llmSkillsLogic = kea<llmSkillsLogicType>([
    path(['scenes', 'llm-analytics', 'llmSkillsLogic']),
    props({} as LLMSkillsLogicProps),
    key((props) => props.tabId ?? 'default'),

    actions({
        setFilters: (filters: Partial<SkillFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadSkills: (debounce: boolean = true) => ({ debounce }),
        deleteSkill: (skillName: string) => ({ skillName }),
        duplicateSkill: (skillName: string, newName: string) => ({ skillName, newName }),
    }),

    reducers({
        rawFilters: [
            null as Partial<SkillFilters> | null,
            {
                setFilters: (state, { filters, merge }) =>
                    cleanFilters({
                        ...(merge ? state || {} : {}),
                        ...filters,
                        ...('page' in filters ? {} : { page: 1 }),
                    }),
            },
        ],
    }),

    loaders(({ values }) => ({
        skills: [
            { results: [], count: 0 } as PaginatedLLMSkillListListApi,
            {
                loadSkills: async ({ debounce }, breakpoint) => {
                    if (debounce && values.skills.results.length > 0) {
                        await breakpoint(300)
                    }

                    const { filters } = values
                    const params = {
                        search: filters.search,
                        order_by: filters.order_by,
                        offset: Math.max(0, (filters.page - 1) * SKILLS_PER_PAGE),
                        limit: SKILLS_PER_PAGE,
                        created_by_id: filters.created_by_id,
                    }

                    if (
                        sceneLogic.findMounted()?.values.activeSceneId === 'LLMAnalytics' &&
                        router.values.lastMethod !== 'POP' &&
                        values.skills.results.length > 0 &&
                        values.rawFilters?.page !== filters.page
                    ) {
                        window.scrollTo(0, 0)
                    }

                    return await llmSkillsList(String(ApiConfig.getCurrentTeamId()), params)
                },
            },
        ],
    })),

    selectors({
        filters: [
            (s) => [s.rawFilters],
            (rawFilters: Partial<SkillFilters> | null): SkillFilters => cleanFilters(rawFilters || {}),
        ],

        count: [(s) => [s.skills], (skills: PaginatedLLMSkillListListApi) => skills.count],

        sorting: [
            (s) => [s.filters],
            (filters: SkillFilters): Sorting | null => {
                if (!filters.order_by) {
                    return { columnKey: 'created_at', order: -1 }
                }

                return filters.order_by.startsWith('-')
                    ? { columnKey: filters.order_by.slice(1), order: -1 }
                    : { columnKey: filters.order_by, order: 1 }
            },
        ],

        pagination: [
            (s) => [s.filters, s.count],
            (filters: SkillFilters, count: number): PaginationManual => ({
                controlled: true,
                pageSize: SKILLS_PER_PAGE,
                currentPage: filters.page,
                entryCount: count,
            }),
        ],

        skillCountLabel: [
            (s) => [s.filters, s.count],
            (filters, count) => {
                const start = (filters.page - 1) * SKILLS_PER_PAGE + 1
                const end = Math.min(filters.page * SKILLS_PER_PAGE, count)

                return count === 0 ? '0 skills' : `${start}-${end} of ${count} skill${count === 1 ? '' : 's'}`
            },
        ],
    }),

    listeners(({ asyncActions, values, selectors }) => ({
        setFilters: async ({ debounce }, _, __, previousState) => {
            const oldFilters = selectors.filters(previousState)
            const { filters } = values

            if (!objectsEqual(oldFilters, filters)) {
                await asyncActions.loadSkills(debounce)
            }
        },

        deleteSkill: async ({ skillName }) => {
            try {
                await llmSkillsNameArchiveCreate(String(ApiConfig.getCurrentTeamId()), skillName)
                lemonToast.info(`${skillName || 'Skill'} has been archived.`)
                await asyncActions.loadSkills(false)
            } catch (e) {
                console.error('Failed to archive skill', e)
                lemonToast.error('Failed to archive skill')
            }
        },

        duplicateSkill: async ({ skillName, newName }) => {
            try {
                await llmSkillsNameDuplicateCreate(String(ApiConfig.getCurrentTeamId()), skillName, {
                    new_name: newName,
                })
                lemonToast.success(`Skill duplicated as "${newName}".`)
                router.actions.push(urls.llmAnalyticsSkill(newName))
            } catch (e) {
                console.error('Failed to duplicate skill', e)
                lemonToast.error('Failed to duplicate skill')
            }
        },
    })),

    tabAwareActionToUrl(({ values }) => {
        const changeUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] | void => {
            const nextValues = {
                ...cleanPagedSearchOrderParams(values.filters),
                created_by_id: values.filters.created_by_id,
            }
            const urlValues = cleanFilters(router.values.searchParams)

            if (!objectsEqual(values.filters, urlValues)) {
                return [urls.llmAnalyticsSkills(), nextValues, {}, { replace: true }]
            }
        }

        return { setFilters: changeUrl }
    }),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.llmAnalyticsSkills()]: (_, searchParams, __, { method }) => {
            const newFilters = cleanFilters(searchParams)
            const forceReload = typeof searchParams?.[LLM_SKILLS_FORCE_RELOAD_PARAM] === 'string'
            if (!objectsEqual(values.filters, newFilters)) {
                actions.setFilters(newFilters, false)
            } else if (forceReload || method !== 'REPLACE') {
                actions.loadSkills(false)
            }

            if (forceReload) {
                const nextSearchParams = { ...searchParams }
                delete nextSearchParams[LLM_SKILLS_FORCE_RELOAD_PARAM]
                router.actions.replace(urls.llmAnalyticsSkills(), nextSearchParams)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadSkills()
    }),
])
