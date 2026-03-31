import {
    actions,
    afterMount,
    beforeUnmount,
    connect,
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
import { combineUrl, router } from 'kea-router'

import api, { ApiError } from '~/lib/api'
import { lemonToast } from '~/lib/lemon-ui/LemonToast/LemonToast'
import { tabAwareUrlToAction } from '~/lib/logic/scenes/tabAwareUrlToAction'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import {
    DataTableNode,
    InsightVizNode,
    NodeKind,
    ProductIntentContext,
    ProductKey,
    TracesQuery,
} from '~/queries/schema/schema-general'
import { isTracesQuery } from '~/queries/utils'
import { teamLogic } from '~/scenes/teamLogic'
import { urls } from '~/scenes/urls'
import {
    AnyPropertyFilter,
    Breadcrumb,
    ChartDisplayType,
    LLMPrompt,
    LLMPromptResolveResponse,
    LLMPromptVersionSummary,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import type { llmPromptLogicType } from './llmPromptLogicType'
import { llmPromptsLogic } from './llmPromptsLogic'
import { LLM_PROMPTS_FORCE_RELOAD_PARAM } from './llmPromptsLogic'

export enum PromptMode {
    View = 'view',
    Edit = 'edit',
}

export enum PromptAnalyticsScope {
    Selected = 'selected',
    AllVersions = 'all_versions',
}

export interface PromptLogicProps {
    promptName: string | 'new'
    mode?: PromptMode
    selectedVersion?: number | null
    tabId?: string
}

export interface PromptFormValues {
    name: string
    prompt: string
}

export interface ResolvedLLMPrompt extends LLMPrompt {
    versions: LLMPromptVersionSummary[]
    has_more: boolean
}

export function isPrompt(prompt: LLMPrompt | ResolvedLLMPrompt | PromptFormValues | null): prompt is ResolvedLLMPrompt {
    return prompt !== null && 'id' in prompt
}

const DEFAULT_PROMPT_FORM_VALUES: PromptFormValues = {
    name: '',
    prompt: '',
}

const PROMPT_FETCHED_EVENT = '$llm_prompt_fetched'
const PROMPT_VERSIONS_LIMIT = 50
export const PROMPT_NAME_MAX_LENGTH = 255
const DEFAULT_PROMPT_ANALYTICS_DATE_FROM = '-1d'
const STALE_PROMPT_ERROR_MESSAGE =
    'This prompt changed while you were editing it. Review the latest version and try again.'

async function fetchResolvedPrompt(
    promptName: string,
    params?: { version?: number; offset?: number; before_version?: number; limit?: number }
): Promise<ResolvedLLMPrompt> {
    return getResolvedPrompt(
        await api.llmPrompts.resolveByName(promptName, {
            ...params,
            limit: params?.limit ?? PROMPT_VERSIONS_LIMIT,
        })
    )
}

async function refreshLatestPromptState(
    promptName: string,
    actions: llmPromptLogicType['actions']
): Promise<ResolvedLLMPrompt> {
    const latestPrompt = await fetchResolvedPrompt(promptName)
    actions.setPrompt(latestPrompt)
    actions.setPromptFormValues(getPromptFormDefaults(latestPrompt))
    return latestPrompt
}

function getResolvedPrompt(response: LLMPromptResolveResponse): ResolvedLLMPrompt {
    return {
        ...response.prompt,
        versions: response.versions,
        has_more: response.has_more,
    }
}

function buildPromptVersionSummary(prompt: LLMPrompt, isLatest: boolean): LLMPromptVersionSummary {
    return {
        id: prompt.id,
        version: prompt.version,
        created_by: prompt.created_by,
        created_at: prompt.created_at,
        is_latest: isLatest,
    }
}

export function getApiErrorDetail(error: unknown): string | undefined {
    if (error !== null && typeof error === 'object' && 'detail' in error && typeof error.detail === 'string') {
        return error.detail
    }
    return undefined
}

function isNameFieldValidationError(error: unknown): error is { attr: 'name'; detail: string } {
    return (
        error !== null &&
        typeof error === 'object' &&
        'attr' in error &&
        error.attr === 'name' &&
        'detail' in error &&
        typeof error.detail === 'string'
    )
}

export const llmPromptLogic = kea<llmPromptLogicType>([
    path(['scenes', 'llm-analytics', 'llmPromptLogic']),
    props({ promptName: 'new' } as PromptLogicProps),
    key(
        ({ promptName, selectedVersion, tabId }) =>
            `prompt-${promptName}:${selectedVersion ?? 'latest'}::${tabId ?? 'default'}`
    ),
    connect(() => ({
        actions: [teamLogic, ['addProductIntent']],
    })),

    actions({
        setPrompt: (prompt: ResolvedLLMPrompt | PromptFormValues) => ({ prompt }),
        deletePrompt: true,
        loadMoreVersions: true,
        setVersionsLoading: (versionsLoading: boolean) => ({ versionsLoading }),
        setMode: (mode: PromptMode) => ({ mode }),
        setAnalyticsScope: (analyticsScope: PromptAnalyticsScope) => ({ analyticsScope }),
        setRelatedTracesQuery: (query: DataTableNode) => ({ query }),
        toggleMarkdownRendering: true,
        setCompareVersion: (compareVersion: number | null) => ({ compareVersion }),
    }),

    reducers(({ props }) => ({
        prompt: [
            null as ResolvedLLMPrompt | PromptFormValues | null,
            {
                loadPromptSuccess: (_, { prompt }) => prompt,
                setPrompt: (_, { prompt }) => prompt,
            },
        ],
        versionsLoading: [
            false,
            {
                loadMoreVersions: () => true,
                setVersionsLoading: (_, { versionsLoading }) => versionsLoading,
                loadPromptSuccess: () => false,
            },
        ],
        mode: [
            props.mode ?? PromptMode.View,
            {
                setMode: (_, { mode }) => mode,
            },
        ],
        analyticsScope: [
            PromptAnalyticsScope.Selected as PromptAnalyticsScope,
            {
                setAnalyticsScope: (_, { analyticsScope }) => analyticsScope,
            },
        ],
        relatedTracesQueryOverride: [
            null as DataTableNode | null,
            {
                setRelatedTracesQuery: (_, { query }) => query,
            },
        ],
        isRenderingMarkdown: [
            true,
            {
                toggleMarkdownRendering: (state) => !state,
                setMode: (_, { mode }) => mode !== PromptMode.Edit,
            },
        ],
        compareVersion: [
            null as number | null,
            {
                setCompareVersion: (_, { compareVersion }) => compareVersion,
                loadPromptSuccess: () => null,
            },
        ],
        comparePrompt: [
            null as LLMPrompt | null,
            {
                setCompareVersion: (state, { compareVersion }) => (compareVersion === null ? null : state),
                loadPromptSuccess: () => null,
            },
        ],
    })),

    loaders(({ props }) => ({
        prompt: {
            __default: null as ResolvedLLMPrompt | PromptFormValues | null,
            loadPrompt: async () =>
                fetchResolvedPrompt(props.promptName, {
                    version: props.selectedVersion ?? undefined,
                }),
        },
        comparePrompt: {
            __default: null as LLMPrompt | null,
            loadComparePrompt: async (version: number) => {
                const resolved = await fetchResolvedPrompt(props.promptName, { version, limit: 1 })
                return resolved as LLMPrompt
            },
        },
    })),

    forms(({ actions, props, values }) => ({
        promptForm: {
            defaults: DEFAULT_PROMPT_FORM_VALUES,
            options: { showErrorsOnTouch: true },

            errors: ({ name, prompt }) => ({
                name: !name?.trim()
                    ? 'Name is required'
                    : name.toLowerCase() === 'new'
                      ? "'new' is a reserved name and cannot be used"
                      : name.length > PROMPT_NAME_MAX_LENGTH
                        ? `Name must be ${PROMPT_NAME_MAX_LENGTH} characters or fewer`
                        : !/^[a-zA-Z0-9_-]+$/.test(name)
                          ? 'Only letters, numbers, hyphens (-), and underscores (_) are allowed'
                          : undefined,
                prompt: !prompt?.trim() ? 'Prompt content is required' : undefined,
            }),

            submit: async (formValues) => {
                const isNew = props.promptName === 'new'

                try {
                    let savedPrompt: LLMPrompt

                    if (isNew) {
                        savedPrompt = await api.llmPrompts.create({
                            name: formValues.name,
                            prompt: formValues.prompt,
                        })
                        llmPromptsLogic.findMounted()?.actions.loadPrompts(false)
                        lemonToast.success('Prompt created successfully')
                        router.actions.replace(urls.llmAnalyticsPrompt(savedPrompt.name))

                        void actions.addProductIntent({
                            product_type: ProductKey.LLM_PROMPTS,
                            intent_context: ProductIntentContext.LLM_PROMPT_CREATED,
                        })
                    } else {
                        const currentPrompt = values.prompt

                        if (!isPrompt(currentPrompt)) {
                            throw new Error('Cannot publish prompt version: prompt data not loaded')
                        }

                        savedPrompt = await api.llmPrompts.update(props.promptName, {
                            prompt: formValues.prompt,
                            base_version: currentPrompt.latest_version,
                        })
                        llmPromptsLogic.findMounted()?.actions.loadPrompts(false)
                        lemonToast.success('Prompt version published successfully')

                        const optimisticVersions = [
                            buildPromptVersionSummary(savedPrompt, true),
                            ...currentPrompt.versions
                                .filter((version) => version.id !== savedPrompt.id)
                                .map((version) => ({ ...version, is_latest: false })),
                        ]

                        actions.setPrompt({
                            ...savedPrompt,
                            versions: optimisticVersions,
                            has_more: currentPrompt.has_more,
                        })
                        actions.setPromptFormValues(getPromptFormDefaults(savedPrompt))
                        actions.setMode(PromptMode.View)
                        router.actions.replace(urls.llmAnalyticsPrompt(props.promptName))

                        // PATCH already succeeded, so keep optimistic state even if follow-up read fails.
                        try {
                            await refreshLatestPromptState(props.promptName, actions)
                        } catch {}
                    }

                    actions.setMode(PromptMode.View)
                    if (isNew) {
                        actions.setPrompt({
                            ...savedPrompt,
                            versions: [],
                            has_more: false,
                        })
                        actions.setPromptFormValues(getPromptFormDefaults(savedPrompt))
                    }
                } catch (error: unknown) {
                    if (isNameFieldValidationError(error)) {
                        actions.setPromptFormManualErrors({ name: error.detail })
                        throw error
                    }

                    if (error instanceof ApiError && error.status === 409) {
                        try {
                            await refreshLatestPromptState(props.promptName, actions)
                        } catch {}

                        lemonToast.error(error.detail || STALE_PROMPT_ERROR_MESSAGE)
                        throw error
                    }

                    lemonToast.error(getApiErrorDetail(error) || 'Failed to save prompt')
                    throw error
                }
            },
        },
    })),

    selectors({
        isNewPrompt: [() => [(_, props) => props], (props) => props.promptName === 'new'],

        isPromptMissing: [
            (s) => [s.prompt, s.promptLoading],
            (prompt, promptLoading) => !promptLoading && prompt === null,
        ],

        shouldDisplaySkeleton: [
            (s) => [s.prompt, s.promptLoading],
            (prompt, promptLoading) => !prompt && promptLoading,
        ],

        isHistoricalVersion: [(s) => [s.prompt], (prompt) => (isPrompt(prompt) ? !prompt.is_latest : false)],

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
            (s) => [s.prompt, router.selectors.searchParams],
            (prompt: LLMPrompt | PromptFormValues | null, searchParams: Record<string, any>): Breadcrumb[] => [
                {
                    name: 'Prompts',
                    path: combineUrl(urls.llmAnalyticsPrompts(), searchParams).url,
                    key: 'LLMAnalyticsPrompts',
                    iconType: 'llm_prompts',
                },
                {
                    name:
                        prompt && 'name' in prompt
                            ? isPrompt(prompt)
                                ? `${prompt.name} v${prompt.version}`
                                : prompt.name || 'New prompt'
                            : 'New prompt',
                    key: 'LLMAnalyticsPrompt',
                    iconType: 'llm_prompts',
                },
            ],
        ],

        isViewMode: [
            (s) => [s.mode, (_, props) => props],
            (mode, props) => props.promptName !== 'new' && mode === PromptMode.View,
        ],

        isEditMode: [
            (s) => [s.mode, (_, props) => props],
            (mode, props) => props.promptName === 'new' || mode === PromptMode.Edit,
        ],

        versions: [(s) => [s.prompt], (prompt): LLMPromptVersionSummary[] => (isPrompt(prompt) ? prompt.versions : [])],

        canLoadMoreVersions: [(s) => [s.prompt], (prompt) => (isPrompt(prompt) ? prompt.has_more : false)],

        isDiffVisible: [(s) => [s.compareVersion], (compareVersion): boolean => compareVersion !== null],

        canCompareVersions: [(s) => [s.prompt], (prompt): boolean => isPrompt(prompt) && prompt.version_count > 1],

        compareVersionOptions: [
            (s) => [s.prompt, s.versions],
            (prompt, versions: LLMPromptVersionSummary[]): Array<{ value: number; label: string }> => {
                if (!isPrompt(prompt)) {
                    return []
                }
                return versions
                    .filter((v) => v.version !== prompt.version)
                    .map((v) => ({
                        value: v.version,
                        label: `v${v.version}${v.is_latest ? ' (latest)' : ''}`,
                    }))
            },
        ],

        tracePropertyFilters: [
            (s) => [s.prompt, s.analyticsScope],
            (prompt, analyticsScope): AnyPropertyFilter[] => {
                if (!isPrompt(prompt)) {
                    return []
                }

                if (analyticsScope === PromptAnalyticsScope.Selected) {
                    return [
                        {
                            type: PropertyFilterType.Event,
                            key: '$ai_prompt_name',
                            value: prompt.name,
                            operator: PropertyOperator.Exact,
                        },
                        {
                            type: PropertyFilterType.Event,
                            key: '$ai_prompt_version',
                            value: prompt.version,
                            operator: PropertyOperator.Exact,
                        },
                    ]
                }

                return [
                    {
                        type: PropertyFilterType.Event,
                        key: '$ai_prompt_name',
                        value: prompt.name,
                        operator: PropertyOperator.Exact,
                    },
                ]
            },
        ],

        defaultRelatedTracesQuery: [
            (s) => [s.prompt, s.tracePropertyFilters],
            (prompt, tracePropertyFilters): DataTableNode | null => {
                if (!isPrompt(prompt)) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.TracesQuery,
                        dateRange: {
                            date_from: DEFAULT_PROMPT_ANALYTICS_DATE_FROM,
                            date_to: undefined,
                        },
                        filterTestAccounts: false,
                        filterSupportTraces: true,
                        properties: tracePropertyFilters,
                    },
                    columns: [
                        'id',
                        'traceName',
                        'promptVersion',
                        'person',
                        'errors',
                        'totalLatency',
                        'usage',
                        'totalCost',
                        'timestamp',
                    ],
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
        relatedTracesQuery: [
            (s) => [s.defaultRelatedTracesQuery, s.relatedTracesQueryOverride],
            (defaultRelatedTracesQuery, relatedTracesQueryOverride): DataTableNode | null => {
                if (!defaultRelatedTracesQuery) {
                    return null
                }
                if (!relatedTracesQueryOverride) {
                    return defaultRelatedTracesQuery
                }
                if (
                    !isTracesQuery(defaultRelatedTracesQuery.source) ||
                    !isTracesQuery(relatedTracesQueryOverride.source)
                ) {
                    return defaultRelatedTracesQuery
                }

                return {
                    ...defaultRelatedTracesQuery,
                    ...relatedTracesQueryOverride,
                    source: {
                        ...(defaultRelatedTracesQuery.source as TracesQuery),
                        ...(relatedTracesQueryOverride.source as TracesQuery),
                        properties: defaultRelatedTracesQuery.source.properties,
                    },
                    columns: defaultRelatedTracesQuery.columns,
                }
            },
        ],

        viewAllTracesUrl: [
            (s) => [s.prompt, s.relatedTracesQuery, s.tracePropertyFilters],
            (prompt, relatedTracesQuery, tracePropertyFilters): string => {
                if (!isPrompt(prompt)) {
                    return urls.llmAnalyticsTraces()
                }

                if (relatedTracesQuery && isTracesQuery(relatedTracesQuery.source)) {
                    return combineUrl(urls.llmAnalyticsTraces(), {
                        filters: relatedTracesQuery.source.properties ?? tracePropertyFilters,
                        date_from: relatedTracesQuery.source.dateRange?.date_from ?? DEFAULT_PROMPT_ANALYTICS_DATE_FROM,
                        date_to: relatedTracesQuery.source.dateRange?.date_to ?? undefined,
                    }).url
                }

                return combineUrl(urls.llmAnalyticsTraces(), {
                    filters: tracePropertyFilters,
                    date_from: DEFAULT_PROMPT_ANALYTICS_DATE_FROM,
                }).url
            },
        ],

        promptUsagePropertyFilter: [
            (s) => [s.prompt, s.analyticsScope],
            (prompt, analyticsScope): AnyPropertyFilter[] => {
                if (!isPrompt(prompt)) {
                    return []
                }

                if (analyticsScope === PromptAnalyticsScope.Selected) {
                    return [
                        {
                            key: 'prompt_id',
                            type: PropertyFilterType.Event,
                            value: prompt.id,
                            operator: PropertyOperator.Exact,
                        },
                    ]
                }

                return [
                    {
                        key: 'prompt_name',
                        type: PropertyFilterType.Event,
                        value: prompt.name,
                        operator: PropertyOperator.Exact,
                    },
                ]
            },
        ],

        promptUsageTrendQuery: [
            (s) => [s.prompt, s.promptUsagePropertyFilter, s.analyticsScope],
            (
                prompt: PromptFormValues | ResolvedLLMPrompt | null,
                promptUsagePropertyFilter: AnyPropertyFilter[],
                analyticsScope: PromptAnalyticsScope
            ): InsightVizNode => {
                void prompt
                void analyticsScope

                return {
                    kind: NodeKind.InsightVizNode,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            { kind: NodeKind.EventsNode, event: PROMPT_FETCHED_EVENT, name: PROMPT_FETCHED_EVENT },
                        ],
                        properties: promptUsagePropertyFilter,
                        dateRange: {
                            date_from: DEFAULT_PROMPT_ANALYTICS_DATE_FROM,
                        },
                        interval: 'day',
                        trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
                    },
                    full: false,
                    showLastComputation: true,
                    showLastComputationRefresh: true,
                }
            },
        ],

        promptUsageLogQuery: [
            (s) => [s.prompt, s.promptUsagePropertyFilter, s.analyticsScope],
            (
                prompt: PromptFormValues | ResolvedLLMPrompt | null,
                promptUsagePropertyFilter: AnyPropertyFilter[],
                analyticsScope: PromptAnalyticsScope
            ): DataTableNode => {
                void prompt
                void analyticsScope

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        event: PROMPT_FETCHED_EVENT,
                        properties: promptUsagePropertyFilter,
                        select: [
                            ...defaultDataTableColumns(NodeKind.EventsQuery),
                            'properties.prompt_name',
                            'properties.prompt_version',
                        ],
                        after: DEFAULT_PROMPT_ANALYTICS_DATE_FROM,
                    },
                    full: false,
                    showDateRange: true,
                    showReload: true,
                }
            },
        ],
    }),

    listeners(({ actions, props, values }) => ({
        deletePrompt: async () => {
            if (props.promptName !== 'new' && values.prompt && isPrompt(values.prompt)) {
                try {
                    await api.llmPrompts.archiveByName(values.prompt.name)
                    lemonToast.info(`${values.prompt.name || 'Prompt'} has been archived.`)
                    llmPromptsLogic.findMounted()?.actions.loadPrompts(false)
                    router.actions.replace(urls.llmAnalyticsPrompts(), {
                        ...router.values.searchParams,
                        [LLM_PROMPTS_FORCE_RELOAD_PARAM]: String(Date.now()),
                    })
                } catch {
                    lemonToast.error('Failed to archive prompt')
                }
            }
        },

        loadMoreVersions: async () => {
            if (props.promptName === 'new' || !isPrompt(values.prompt)) {
                actions.setVersionsLoading(false)
                return
            }

            try {
                const oldestLoadedVersion = values.prompt.versions[values.prompt.versions.length - 1]?.version
                if (!oldestLoadedVersion) {
                    actions.setVersionsLoading(false)
                    return
                }

                const response = await fetchResolvedPrompt(props.promptName, {
                    version: values.prompt.version,
                    before_version: oldestLoadedVersion,
                })

                const existingVersionIds = new Set(values.prompt.versions.map((version) => version.id))
                const appendedVersions = response.versions.filter((version) => !existingVersionIds.has(version.id))

                actions.setPrompt({
                    ...response,
                    versions: [...values.prompt.versions, ...appendedVersions],
                    has_more: response.has_more,
                })
            } catch {
                lemonToast.error('Failed to load more versions')
            } finally {
                actions.setVersionsLoading(false)
            }
        },

        loadPromptSuccess: ({ prompt }) => {
            if (prompt && isPrompt(prompt)) {
                actions.resetPromptForm()
                actions.setPromptFormValues(getPromptFormDefaults(prompt))
            }
        },

        setCompareVersion: ({ compareVersion }) => {
            if (compareVersion !== null) {
                actions.loadComparePrompt(compareVersion)
            }
        },

        loadComparePromptFailure: () => {
            lemonToast.error('Failed to load comparison version')
        },
    })),

    defaults(
        ({
            props,
        }): {
            prompt: PromptFormValues | ResolvedLLMPrompt | null
            promptForm: PromptFormValues
            versionsLoading: boolean
        } => {
            if (props.promptName === 'new') {
                return {
                    prompt: DEFAULT_PROMPT_FORM_VALUES,
                    promptForm: DEFAULT_PROMPT_FORM_VALUES,
                    versionsLoading: false,
                }
            }

            const existingPrompt = findExistingPrompt(props.promptName)

            if (existingPrompt) {
                return {
                    prompt: { ...existingPrompt, versions: [], has_more: false },
                    promptForm: getPromptFormDefaults(existingPrompt),
                    versionsLoading: false,
                }
            }

            return {
                prompt: null,
                promptForm: DEFAULT_PROMPT_FORM_VALUES,
                versionsLoading: false,
            }
        }
    ),

    afterMount(({ actions, values }) => {
        if (values.isNewPrompt) {
            actions.setPrompt(DEFAULT_PROMPT_FORM_VALUES)
            actions.resetPromptForm(DEFAULT_PROMPT_FORM_VALUES)
        } else {
            actions.loadPrompt()
        }
    }),

    beforeUnmount(({ actions, props }) => {
        if (props.promptName === 'new') {
            actions.setPromptFormValues(DEFAULT_PROMPT_FORM_VALUES)
            return
        }

        const existing = findExistingPrompt(props.promptName)
        actions.setPromptFormValues(existing ? getPromptFormDefaults(existing) : DEFAULT_PROMPT_FORM_VALUES)
    }),

    tabAwareUrlToAction(({ actions, values }) => ({
        '/llm-analytics/prompts/:name': (_, __, ___, { method }) => {
            if (method === 'PUSH' && values.isNewPrompt) {
                actions.setPrompt(DEFAULT_PROMPT_FORM_VALUES)
                actions.resetPromptForm(DEFAULT_PROMPT_FORM_VALUES)
                return
            }

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

function findExistingPrompt(promptName: string): LLMPrompt | undefined {
    return llmPromptsLogic.findMounted()?.values.prompts.results.find((prompt) => prompt.name === promptName)
}
