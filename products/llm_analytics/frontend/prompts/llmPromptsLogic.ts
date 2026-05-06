import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api, { CountedPaginatedResponse } from '~/lib/api'
import { Sorting } from '~/lib/lemon-ui/LemonTable'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { tabAwareActionToUrl } from '~/lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from '~/lib/logic/scenes/tabAwareUrlToAction'
import { objectsEqual } from '~/lib/utils'
import { sceneLogic } from '~/scenes/sceneLogic'
import { urls } from '~/scenes/urls'
import { LLMPrompt } from '~/types'

import { cleanPagedSearchOrderParams } from '../utils'
import type { llmPromptsLogicType } from './llmPromptsLogicType'

export const PROMPTS_PER_PAGE = 30
export const LLM_PROMPTS_FORCE_RELOAD_PARAM = 'llm_prompts_force_reload'

export interface PromptFilters {
    page: number
    search: string
    order_by: string
    created_by_id?: number
}

function cleanFilters(values: Partial<PromptFilters>): PromptFilters {
    return {
        page: parseInt(String(values.page)) || 1,
        search: String(values.search || ''),
        order_by: values.order_by || '-created_at',
        created_by_id: values.created_by_id ? Number(values.created_by_id) : undefined,
    }
}

export interface LLMPromptsLogicProps {
    tabId?: string
}

export const llmPromptsLogic = kea<llmPromptsLogicType>([
    path(['scenes', 'llm-analytics', 'llmPromptsLogic']),
    props({} as LLMPromptsLogicProps),
    key((props) => props.tabId ?? 'default'),

    actions({
        setFilters: (filters: Partial<PromptFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadPrompts: (debounce: boolean = true) => ({ debounce }),
        deletePrompt: (promptName: string) => ({ promptName }),
        duplicatePrompt: (promptName: string, newName: string) => ({ promptName, newName }),
    }),

    reducers({
        rawFilters: [
            null as Partial<PromptFilters> | null,
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
        prompts: [
            { results: [], count: 0, offset: 0 } as CountedPaginatedResponse<LLMPrompt>,
            {
                loadPrompts: async ({ debounce }, breakpoint) => {
                    if (debounce && values.prompts.results.length > 0) {
                        await breakpoint(300)
                    }

                    const { filters } = values
                    const params = {
                        search: filters.search,
                        order_by: filters.order_by,
                        offset: Math.max(0, (filters.page - 1) * PROMPTS_PER_PAGE),
                        limit: PROMPTS_PER_PAGE,
                        created_by_id: filters.created_by_id,
                    }

                    if (
                        sceneLogic.findMounted()?.values.activeSceneId === 'LLMAnalytics' &&
                        router.values.lastMethod !== 'POP' &&
                        values.prompts.results.length > 0 &&
                        values.rawFilters?.page !== filters.page
                    ) {
                        window.scrollTo(0, 0)
                    }

                    const response = await api.llmPrompts.list(params)
                    return response
                },
            },
        ],
    })),

    selectors({
        filters: [
            (s) => [s.rawFilters],
            (rawFilters: Partial<PromptFilters> | null): PromptFilters => cleanFilters(rawFilters || {}),
        ],

        count: [(s) => [s.prompts], (prompts: CountedPaginatedResponse<LLMPrompt>) => prompts.count],

        sorting: [
            (s) => [s.filters],
            (filters: PromptFilters): Sorting | null => {
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
            (filters: PromptFilters, count: number): PaginationManual => ({
                controlled: true,
                pageSize: PROMPTS_PER_PAGE,
                currentPage: filters.page,
                entryCount: count,
            }),
        ],

        promptCountLabel: [
            (s) => [s.filters, s.count],
            (filters, count) => {
                const start = (filters.page - 1) * PROMPTS_PER_PAGE + 1
                const end = Math.min(filters.page * PROMPTS_PER_PAGE, count)

                return count === 0 ? '0 prompts' : `${start}-${end} of ${count} prompt${count === 1 ? '' : 's'}`
            },
        ],
    }),

    listeners(({ asyncActions, values, selectors }) => ({
        setFilters: async ({ debounce }, _, __, previousState) => {
            const oldFilters = selectors.filters(previousState)
            const { filters } = values

            if (!objectsEqual(oldFilters, filters)) {
                await asyncActions.loadPrompts(debounce)
            }
        },

        deletePrompt: async ({ promptName }) => {
            try {
                await api.llmPrompts.archiveByName(promptName)
                lemonToast.info(`${promptName || 'Prompt'} has been archived.`)
                await asyncActions.loadPrompts(false)
            } catch {
                lemonToast.error('Failed to archive prompt')
            }
        },

        duplicatePrompt: async ({ promptName, newName }) => {
            try {
                await api.llmPrompts.duplicateByName(promptName, newName)
                lemonToast.success(`Prompt duplicated as "${newName}".`)
                router.actions.push(urls.llmAnalyticsPrompt(newName))
            } catch {
                lemonToast.error('Failed to duplicate prompt')
            }
        },
    })),

    tabAwareActionToUrl(({ values }) => {
        const changeUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] | void => {
            const nextValues = cleanPagedSearchOrderParams(values.filters)
            const urlValues = cleanFilters(router.values.searchParams)

            if (!objectsEqual(values.filters, urlValues)) {
                return [urls.llmAnalyticsPrompts(), nextValues, {}, { replace: true }]
            }
        }

        return { setFilters: changeUrl }
    }),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.llmAnalyticsPrompts()]: (_, searchParams, __, { method }) => {
            const newFilters = cleanFilters(searchParams)
            const forceReload = typeof searchParams?.[LLM_PROMPTS_FORCE_RELOAD_PARAM] === 'string'
            if (!objectsEqual(values.filters, newFilters)) {
                actions.setFilters(newFilters, false)
            } else if (forceReload || method !== 'REPLACE') {
                actions.loadPrompts(false)
            }

            if (forceReload) {
                const nextSearchParams = { ...searchParams }
                delete nextSearchParams[LLM_PROMPTS_FORCE_RELOAD_PARAM]
                router.actions.replace(urls.llmAnalyticsPrompts(), nextSearchParams)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadPrompts()
    }),
])
