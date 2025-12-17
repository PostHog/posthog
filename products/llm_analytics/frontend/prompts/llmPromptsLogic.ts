import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api, { CountedPaginatedResponse } from '~/lib/api'
import { Sorting } from '~/lib/lemon-ui/LemonTable'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { PaginationManual } from '~/lib/lemon-ui/PaginationControl'
import { objectsEqual } from '~/lib/utils'
import { sceneLogic } from '~/scenes/sceneLogic'
import { urls } from '~/scenes/urls'
import { LLMPrompt } from '~/types'

import type { llmPromptsLogicType } from './llmPromptsLogicType'

export const PROMPTS_PER_PAGE = 30

export interface PromptFilters {
    page: number
    search: string
    order_by: string
}

function cleanFilters(values: Partial<PromptFilters>): PromptFilters {
    return {
        page: parseInt(String(values.page)) || 1,
        search: String(values.search || ''),
        order_by: values.order_by || '-created_at',
    }
}

export const llmPromptsLogic = kea<llmPromptsLogicType>([
    path(['scenes', 'llm-analytics', 'llmPromptsLogic']),

    actions({
        setFilters: (filters: Partial<PromptFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadPrompts: (debounce: boolean = true) => ({ debounce }),
        deletePrompt: (promptId: string) => ({ promptId }),
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

        deletePrompt: async ({ promptId }) => {
            try {
                const promptName = values.prompts.results.find((prompt) => prompt.id === promptId)?.name
                await api.llmPrompts.update(promptId, { deleted: true })
                lemonToast.info(`${promptName || 'Prompt'} has been deleted.`)
                await asyncActions.loadPrompts(false)
            } catch {
                lemonToast.error('Failed to delete prompt')
            }
        },
    })),

    actionToUrl(({ values }) => {
        const changeUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] | void => {
            const nextValues = cleanFilters(values.filters)
            const urlValues = cleanFilters(router.values.searchParams)

            if (!objectsEqual(nextValues, urlValues)) {
                return [urls.llmAnalyticsPrompts(), nextValues, {}, { replace: false }]
            }
        }

        return { setFilters: changeUrl }
    }),

    urlToAction(({ actions, values }) => ({
        [urls.llmAnalyticsPrompts()]: (_, searchParams) => {
            const newFilters = cleanFilters(searchParams)

            if (values.rawFilters === null || !objectsEqual(values.filters, newFilters)) {
                actions.setFilters(newFilters, false)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadPrompts()
    }),
])
