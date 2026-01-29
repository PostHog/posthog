import {
    actions,
    afterMount,
    beforeUnmount,
    defaults,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from '~/lib/api'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { urls } from '~/scenes/urls'
import { Breadcrumb, LLMPrompt, PropertyFilterType, PropertyOperator } from '~/types'

import type { llmPromptLogicType } from './llmPromptLogicType'
import { llmPromptsLogic } from './llmPromptsLogic'

export enum PromptMode {
    View = 'view',
    Edit = 'edit',
}

export interface PromptLogicProps {
    promptId: string | 'new'
    mode?: PromptMode
}

export interface PromptFormValues {
    name: string
    prompt: string
}

export function isPrompt(prompt: LLMPrompt | PromptFormValues | null): prompt is LLMPrompt {
    return prompt !== null && 'id' in prompt
}

const DEFAULT_PROMPT_FORM_VALUES: PromptFormValues = {
    name: '',
    prompt: '',
}

export const llmPromptLogic = kea<llmPromptLogicType>([
    path(['scenes', 'llm-analytics', 'llmPromptLogic']),
    props({ promptId: 'new' } as PromptLogicProps),
    key(({ promptId }) => `prompt-${promptId}`),

    actions({
        setPrompt: (prompt: LLMPrompt | PromptFormValues) => ({ prompt }),
        deletePrompt: true,
        setMode: (mode: PromptMode) => ({ mode }),
    }),

    reducers(({ props }) => ({
        prompt: [
            null as LLMPrompt | PromptFormValues | null,
            {
                loadPromptSuccess: (_, { prompt }) => prompt,
                setPrompt: (_, { prompt }) => prompt,
            },
        ],
        mode: [
            props.mode ?? PromptMode.View,
            {
                setMode: (_, { mode }) => mode,
            },
        ],
    })),

    loaders(({ props }) => ({
        prompt: {
            __default: null as LLMPrompt | PromptFormValues | null,
            loadPrompt: () => api.llmPrompts.get(props.promptId),
        },
    })),

    forms(({ actions, props }) => ({
        promptForm: {
            defaults: DEFAULT_PROMPT_FORM_VALUES,
            options: { showErrorsOnTouch: true },

            errors: ({ name, prompt }) => ({
                name: !name?.trim()
                    ? 'Name is required'
                    : !/^[a-zA-Z0-9_-]+$/.test(name)
                      ? 'Only letters, numbers, hyphens (-), and underscores (_) are allowed'
                      : undefined,
                prompt: !prompt?.trim() ? 'Prompt content is required' : undefined,
            }),

            submit: async (formValues) => {
                const isNew = props.promptId === 'new'

                try {
                    let savedPrompt: LLMPrompt

                    if (isNew) {
                        savedPrompt = await api.llmPrompts.create({
                            name: formValues.name,
                            prompt: formValues.prompt,
                        })
                        lemonToast.success('Prompt created successfully')
                    } else {
                        savedPrompt = await api.llmPrompts.update(props.promptId, {
                            name: formValues.name,
                            prompt: formValues.prompt,
                        })
                        lemonToast.success('Prompt updated successfully')
                    }

                    router.actions.replace(urls.llmAnalyticsPrompts())

                    actions.setPrompt(savedPrompt)
                    actions.setPromptFormValues(getPromptFormDefaults(savedPrompt))
                } catch (error: unknown) {
                    // Handle field-specific validation errors from backend
                    if (
                        error !== null &&
                        typeof error === 'object' &&
                        'attr' in error &&
                        error.attr === 'name' &&
                        'detail' in error &&
                        typeof error.detail === 'string'
                    ) {
                        actions.setPromptFormManualErrors({ name: error.detail })
                        throw error
                    }

                    const message =
                        error !== null &&
                        typeof error === 'object' &&
                        'detail' in error &&
                        typeof error.detail === 'string'
                            ? error.detail
                            : 'Failed to save prompt'

                    lemonToast.error(message)
                    throw error
                }
            },
        },
    })),

    selectors({
        isNewPrompt: [() => [(_, props) => props], (props) => props.promptId === 'new'],

        isPromptMissing: [
            (s) => [s.prompt, s.promptLoading],
            (prompt, promptLoading) => !promptLoading && prompt === null,
        ],

        shouldDisplaySkeleton: [
            (s) => [s.prompt, s.promptLoading],
            (prompt, promptLoading) => !prompt && promptLoading,
        ],

        promptVariables: [
            (s) => [s.promptForm],
            (promptForm: PromptFormValues): string[] => {
                const matches = promptForm.prompt.match(/\{\{([^}]+)\}\}/g)

                if (!matches) {
                    return []
                }

                const variables = matches.map((match: string) => match.slice(2, -2).trim())
                return [...new Set(variables)]
            },
        ],

        breadcrumbs: [
            (s) => [s.prompt],
            (prompt): Breadcrumb[] => [
                {
                    name: 'LLM Analytics',
                    path: urls.llmAnalyticsDashboard(),
                    key: 'LLMAnalytics',
                    iconType: 'llm_analytics',
                },
                {
                    name: 'Prompts',
                    path: urls.llmAnalyticsPrompts(),
                    key: 'LLMAnalyticsPrompts',
                    iconType: 'llm_analytics',
                },
                {
                    name: prompt && 'name' in prompt ? prompt.name : 'New prompt',
                    key: 'LLMAnalyticsPrompt',
                    iconType: 'llm_analytics',
                },
            ],
        ],

        isViewMode: [
            (s) => [s.mode, (_, props) => props],
            (mode, props) => props.promptId !== 'new' && mode === PromptMode.View,
        ],

        isEditMode: [
            (s) => [s.mode, (_, props) => props],
            (mode, props) => props.promptId === 'new' || mode === PromptMode.Edit,
        ],

        relatedTracesQuery: [
            (s) => [s.prompt],
            (prompt): DataTableNode | null => {
                if (!isPrompt(prompt)) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.TracesQuery,
                        dateRange: {
                            date_from: '-7d',
                            date_to: undefined,
                        },
                        filterTestAccounts: false,
                        filterSupportTraces: true,
                        properties: [
                            {
                                type: PropertyFilterType.Event,
                                key: '$ai_prompt_name',
                                value: prompt.name,
                                operator: PropertyOperator.Exact,
                            },
                        ],
                    },
                    columns: ['id', 'traceName', 'person', 'errors', 'totalLatency', 'usage', 'totalCost', 'timestamp'],
                    showDateRange: true,
                    showReload: true,
                    showSearch: false,
                    showTestAccountFilters: true,
                    showExport: false,
                    showOpenEditorButton: false,
                    showColumnConfigurator: false,
                }
            },
        ],

        viewAllTracesUrl: [
            (s) => [s.prompt],
            (prompt): string => {
                if (!isPrompt(prompt)) {
                    return urls.llmAnalyticsTraces()
                }

                const filters = [
                    {
                        type: PropertyFilterType.Event,
                        key: '$ai_prompt_name',
                        value: prompt.name,
                        operator: PropertyOperator.Exact,
                    },
                ]

                return `${urls.llmAnalyticsTraces()}?filters=${encodeURIComponent(JSON.stringify(filters))}`
            },
        ],
    }),

    listeners(({ actions, props, values }) => ({
        deletePrompt: async () => {
            if (props.promptId !== 'new') {
                try {
                    await api.llmPrompts.update(props.promptId, { deleted: true })
                    lemonToast.info(`${values.prompt?.name || 'Prompt'} has been deleted.`)
                    router.actions.replace(urls.llmAnalyticsPrompts())
                } catch {
                    lemonToast.error('Failed to delete prompt')
                }
            }
        },

        loadPromptSuccess: ({ prompt }) => {
            if (prompt) {
                actions.resetPromptForm()
                actions.setPromptFormValues(getPromptFormDefaults(prompt as LLMPrompt))
            }
        },
    })),

    defaults(
        ({
            props,
        }): {
            prompt: PromptFormValues | LLMPrompt | null
            promptForm: PromptFormValues
        } => {
            if (props.promptId === 'new') {
                return {
                    prompt: DEFAULT_PROMPT_FORM_VALUES,
                    promptForm: DEFAULT_PROMPT_FORM_VALUES,
                }
            }

            const existingPrompt = findExistingPrompt(props.promptId)

            if (existingPrompt) {
                return {
                    prompt: existingPrompt,
                    promptForm: getPromptFormDefaults(existingPrompt),
                }
            }

            return {
                prompt: null,
                promptForm: DEFAULT_PROMPT_FORM_VALUES,
            }
        }
    ),

    afterMount(({ actions, values }) => {
        if (values.isNewPrompt) {
            // Reset form when mounting the "new" prompt scene to clear any stale values
            actions.resetPromptForm()
        } else {
            actions.loadPrompt()
        }
    }),

    beforeUnmount(({ actions, props }) => {
        if (props.promptId === 'new') {
            actions.setPromptFormValues(DEFAULT_PROMPT_FORM_VALUES)
        } else {
            const existing = findExistingPrompt(props.promptId)

            if (existing) {
                actions.setPromptFormValues(getPromptFormDefaults(existing))
            } else {
                actions.setPromptFormValues(DEFAULT_PROMPT_FORM_VALUES)
            }
        }
    }),

    urlToAction(({ actions, values }) => ({
        '/llm-analytics/prompts/:id': (_, __, ___, { method }) => {
            if (method === 'PUSH' && !values.isNewPrompt) {
                actions.loadPrompt()
            }
        },
    })),
])

function getPromptFormDefaults(prompt: LLMPrompt): PromptFormValues {
    return {
        name: prompt.name,
        prompt: prompt.prompt,
    }
}

function findExistingPrompt(promptId: string): LLMPrompt | undefined {
    return llmPromptsLogic.findMounted()?.values.prompts.results.find((p) => p.id === promptId)
}
