import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { HogQLQuery, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { ChartDisplayType, PropertyFilterType, PropertyOperator } from '~/types'

import { llmAnalyticsSharedLogic } from '../llmAnalyticsSharedLogic'
import { parseTrialProviderKeyId } from '../ModelPicker'
import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import type { llmTaggerLogicType } from './llmTaggerLogicType'
import { llmTaggersLogic } from './llmTaggersLogic'
import {
    getIntervalFromDateRange,
    ModelConfiguration,
    Tagger,
    TaggerConditionSet,
    TaggerConfig,
    TaggerType,
} from './types'

export interface HogTestResult {
    event_uuid: string
    trace_id?: string | null
    input_preview: string
    output_preview: string
    tags: string[]
    reasoning: string
    error: string | null
}

export interface TagRun {
    timestamp: string
    tags: string[]
    reasoning: string
    trace_id: string
    target_event_id: string
    tagger_id: string
    tagger_name: string
}

export interface LLMTaggerLogicProps {
    id: string | 'new'
}

const DEFAULT_TAGGER_CONFIG: TaggerConfig = {
    prompt: '',
    tags: [{ name: '', description: '' }],
    min_tags: 0,
    max_tags: null,
}

const DEFAULT_CONDITION: TaggerConditionSet = {
    id: crypto.randomUUID(),
    rollout_percentage: 100,
    properties: [],
}

export interface TaggerForm {
    name: string
    description: string
    enabled: boolean
    tagger_type: TaggerType
    tagger_config: TaggerConfig
    conditions: TaggerConditionSet[]
    model_configuration: ModelConfiguration | null
}

const DEFAULT_FORM: TaggerForm = {
    name: '',
    description: '',
    enabled: false,
    tagger_type: 'llm',
    tagger_config: DEFAULT_TAGGER_CONFIG,
    conditions: [DEFAULT_CONDITION],
    model_configuration: null,
}

export const llmTaggerLogic = kea<llmTaggerLogicType>([
    path(['products', 'llm_analytics', 'taggers', 'llmTaggerLogic']),
    props({} as LLMTaggerLogicProps),
    key((props) => props.id),

    connect(() => ({
        values: [llmProviderKeysLogic, ['providerKeys'], llmAnalyticsSharedLogic, ['dateFilter']],
        actions: [llmProviderKeysLogic, ['loadProviderKeys'], llmAnalyticsSharedLogic, ['setDates']],
    })),

    actions({
        selectModelFromPicker: (modelId: string, providerKeyId: string) => ({ modelId, providerKeyId }),
        setConditions: (conditions: TaggerConditionSet[]) => ({ conditions }),
        loadTagger: true,
        loadTaggerSuccess: (tagger: Tagger) => ({ tagger }),
        deleteTagger: true,
        addTag: true,
        removeTag: (index: number) => ({ index }),
        updateTag: (index: number, field: 'name' | 'description', value: string) => ({ index, field, value }),
        addCondition: true,
        removeCondition: (index: number) => ({ index }),
        setActiveTab: (tab: 'runs' | 'configuration') => ({ tab }),
        loadTagRuns: true,
        loadTagRunsSuccess: (runs: TagRun[]) => ({ runs }),
        testHogTagger: true,
        testHogTaggerSuccess: (results: HogTestResult[]) => ({ results }),
        clearHogTestResults: true,
    }),

    reducers({
        tagger: [
            null as Tagger | null,
            {
                loadTaggerSuccess: (_, { tagger }) => tagger,
            },
        ],
        taggerLoading: [
            false,
            {
                loadTagger: () => true,
                loadTaggerSuccess: () => false,
            },
        ],
        selectedModel: [
            '' as string,
            {
                selectModelFromPicker: (_, { modelId }) => modelId,
                loadTaggerSuccess: (_, { tagger }) => tagger?.model_configuration?.model || '',
            },
        ],
        selectedPickerProviderKeyId: [
            null as string | null,
            {
                selectModelFromPicker: (_, { providerKeyId }) => providerKeyId,
                loadTaggerSuccess: (_, { tagger }) => tagger?.model_configuration?.provider_key_id || null,
            },
        ],
        activeTab: [
            'runs' as string,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        tagRuns: [
            [] as TagRun[],
            {
                loadTagRunsSuccess: (_, { runs }) => runs,
            },
        ],
        tagRunsLoading: [
            false,
            {
                loadTagRuns: () => true,
                loadTagRunsSuccess: () => false,
            },
        ],
        hogTestResults: [
            null as HogTestResult[] | null,
            {
                testHogTaggerSuccess: (_, { results }) => results,
                clearHogTestResults: () => null,
            },
        ],
        hogTestLoading: [
            false,
            {
                testHogTagger: () => true,
                testHogTaggerSuccess: () => false,
            },
        ],
    }),

    selectors({
        isNewTagger: [(_, props) => [props.id], (id: string) => id === 'new'],

        runsChartQuery: [
            (s, props) => [props.id, s.dateFilter],
            (id: string, dateFilter: { dateFrom: string | null; dateTo: string | null }): TrendsQuery | null => {
                if (id === 'new') {
                    return null
                }

                const dateFrom = dateFilter.dateFrom || '-7d'
                const dateTo = dateFilter.dateTo || null
                const interval = getIntervalFromDateRange(dateFrom)

                return {
                    kind: NodeKind.TrendsQuery,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: '$ai_tag',
                            math: 'total' as any,
                            properties: [
                                {
                                    key: '$ai_tagger_id',
                                    value: id,
                                    operator: PropertyOperator.Exact,
                                    type: PropertyFilterType.Event,
                                },
                            ],
                        },
                    ],
                    breakdownFilter: {
                        // Emit one breakdown row per event. If $ai_tags is empty, bucket under
                        // "(no tag)" so the chart still reflects that the tagger is running even
                        // when no tags matched (otherwise arrayJoin on [] drops the event).
                        breakdown:
                            "arrayJoin(if(length(JSONExtract(ifNull(properties.$ai_tags, '[]'), 'Array(String)')) = 0, ['(no tag)'], JSONExtract(ifNull(properties.$ai_tags, '[]'), 'Array(String)')))",
                        breakdown_type: 'hogql',
                    },
                    trendsFilter: {
                        // Stacked area makes the composition read naturally: total height = run
                        // volume, colored bands = tag share. Handles the "(no tag)" bucket cleanly
                        // without it looking like a stray zero-line.
                        display: ChartDisplayType.ActionsAreaGraph,
                    },
                    dateRange: {
                        date_from: dateFrom,
                        date_to: dateTo,
                    },
                    interval,
                }
            },
        ],
    }),

    forms(({ props }) => ({
        taggerForm: {
            defaults: DEFAULT_FORM,
            errors: (values: TaggerForm) => ({
                name: !values.name ? 'Name is required' : undefined,
                tagger_config:
                    values.tagger_type === 'hog'
                        ? {
                              source: !('source' in values.tagger_config && values.tagger_config.source?.trim())
                                  ? 'Hog source code is required'
                                  : undefined,
                          }
                        : {
                              prompt: !('prompt' in values.tagger_config && values.tagger_config.prompt)
                                  ? 'Prompt is required'
                                  : undefined,
                              // kea-forms expects per-tag errors as an array matching tags[]. The
                              // array type does not allow `undefined` slots, so use `{}` for
                              // tags with no error. Synthesize a single-entry error for the
                              // empty-tags case so the form stays invalid (the UI guardrail
                              // blocks reaching this state, but a programmatic removeTag could).
                              tags:
                                  values.tagger_config.tags.length === 0
                                      ? [{ name: 'At least one tag is required' }]
                                      : values.tagger_config.tags.some((t) => !t.name.trim())
                                        ? values.tagger_config.tags.map((t) =>
                                              !t.name.trim() ? { name: 'All tags must have a name' } : {}
                                          )
                                        : undefined,
                          },
            }),
            submit: async (values: TaggerForm) => {
                const payload = {
                    ...values,
                    tagger_config: {
                        ...values.tagger_config,
                        tags: values.tagger_config.tags.filter((t) => t.name.trim()),
                    },
                }

                if (props.id === 'new') {
                    // nosemgrep: prefer-codegen-api
                    await api.create('api/environments/@current/taggers/', payload)
                    lemonToast.success('Tagger created')
                } else {
                    // nosemgrep: prefer-codegen-api
                    await api.update(`api/environments/@current/taggers/${props.id}/`, payload)
                    lemonToast.success('Tagger updated')
                }
                // Reload list before navigating so the new/updated tagger is visible
                llmTaggersLogic.findMounted()?.actions.loadTaggers()
                router.actions.push(urls.llmAnalyticsTags())
            },
        },
    })),

    listeners(({ props, actions, values }) => ({
        testHogTagger: async () => {
            const config = values.taggerForm.tagger_config
            const source = 'source' in config ? config.source : ''
            if (!source) {
                return
            }
            try {
                const teamId = teamLogic.values.currentTeamId
                // nosemgrep: prefer-codegen-api
                const response = await api.create(`/api/environments/${teamId}/taggers/test_hog/`, {
                    source,
                    sample_count: 5,
                    tags: config.tags.filter((t: { name: string }) => t.name.trim()),
                })
                actions.testHogTaggerSuccess(response.results || [])
            } catch (error) {
                console.error('Hog tagger test failed:', error)
                actions.testHogTaggerSuccess([])
            }
        },
        loadTagRuns: async () => {
            if (props.id === 'new') {
                actions.loadTagRunsSuccess([])
                return
            }
            const dateFrom = values.dateFilter?.dateFrom || '-24h'
            const dateTo = values.dateFilter?.dateTo || null
            // Use a HogQL parameter placeholder rather than string interpolation —
            // props.id comes from the URL path, so interpolating it directly into
            // the query text would open an injection vector.
            const query: HogQLQuery = {
                kind: NodeKind.HogQLQuery,
                query: `
                    SELECT
                        timestamp,
                        properties.$ai_tags as tags,
                        properties.$ai_tag_reasoning as reasoning,
                        properties.$ai_trace_id as trace_id,
                        properties.$ai_target_event_id as target_event_id,
                        properties.$ai_tagger_id as tagger_id,
                        properties.$ai_tagger_name as tagger_name
                    FROM events
                    WHERE event = '$ai_tag'
                      AND properties.$ai_tagger_id = {tagger_id}
                      AND {filters}
                    ORDER BY timestamp DESC
                    LIMIT 100
                `,
                values: { tagger_id: props.id },
                filters: {
                    dateRange: {
                        date_from: dateFrom,
                        date_to: dateTo,
                    },
                },
            }
            try {
                const response = await api.query(query)
                const runs = (response.results || []).map((row: any[]) => ({
                    timestamp: row[0],
                    tags: typeof row[1] === 'string' ? JSON.parse(row[1]) : row[1] || [],
                    reasoning: row[2] || '',
                    trace_id: row[3] || '',
                    target_event_id: row[4] || '',
                    tagger_id: row[5] || '',
                    tagger_name: row[6] || '',
                }))
                actions.loadTagRunsSuccess(runs)
            } catch {
                actions.loadTagRunsSuccess([])
            }
        },
        loadTagger: async () => {
            if (props.id === 'new') {
                return
            }
            // Wrap in try/catch so a failed fetch clears taggerLoading — otherwise
            // the UI is stuck on the skeleton indefinitely on any API error.
            try {
                // nosemgrep: prefer-codegen-api
                const tagger = await api.get(`api/environments/@current/taggers/${props.id}/`)
                actions.loadTaggerSuccess(tagger)
                actions.setTaggerFormValues({
                    name: tagger.name,
                    description: tagger.description || '',
                    enabled: tagger.enabled,
                    tagger_type: tagger.tagger_type || 'llm',
                    tagger_config: tagger.tagger_config,
                    conditions: tagger.conditions.length > 0 ? tagger.conditions : [DEFAULT_CONDITION],
                    model_configuration: tagger.model_configuration,
                })
            } catch (error) {
                lemonToast.error(`Failed to load tagger: ${error instanceof Error ? error.message : String(error)}`)
                actions.loadTaggerSuccess(null as any)
            }
        },
        deleteTagger: async () => {
            if (props.id === 'new') {
                return
            }
            // nosemgrep: prefer-codegen-api
            await api.update(`api/environments/@current/taggers/${props.id}/`, { deleted: true })
            lemonToast.success('Tagger deleted')
            router.actions.push(urls.llmAnalyticsTags())
        },
        addTag: () => {
            const current = values.taggerForm.tagger_config
            actions.setTaggerFormValues({
                tagger_config: {
                    ...current,
                    tags: [...current.tags, { name: '', description: '' }],
                },
            })
        },
        removeTag: ({ index }) => {
            const current = values.taggerForm.tagger_config
            actions.setTaggerFormValues({
                tagger_config: {
                    ...current,
                    tags: current.tags.filter((_, i) => i !== index),
                },
            })
        },
        updateTag: ({ index, field, value }) => {
            const current = values.taggerForm.tagger_config
            const tags = [...current.tags]
            tags[index] = { ...tags[index], [field]: value }
            actions.setTaggerFormValues({
                tagger_config: {
                    ...current,
                    tags,
                },
            })
        },
        addCondition: () => {
            actions.setTaggerFormValues({
                conditions: [
                    ...values.taggerForm.conditions,
                    { id: crypto.randomUUID(), rollout_percentage: 100, properties: [] },
                ],
            })
        },
        removeCondition: ({ index }) => {
            actions.setTaggerFormValues({
                conditions: values.taggerForm.conditions.filter((_, i) => i !== index),
            })
        },
        setConditions: ({ conditions }) => {
            actions.setTaggerFormValues({ conditions })
        },
        selectModelFromPicker: ({ modelId, providerKeyId }) => {
            if (!modelId) {
                return
            }
            const trialProvider = parseTrialProviderKeyId(providerKeyId)
            if (trialProvider) {
                actions.setTaggerFormValues({
                    model_configuration: {
                        provider: trialProvider,
                        model: modelId,
                        provider_key_id: null,
                    },
                })
                return
            }
            const key = values.providerKeys.find((k: LLMProviderKey) => k.id === providerKeyId)
            if (key) {
                actions.setTaggerFormValues({
                    model_configuration: {
                        provider: key.provider,
                        model: modelId,
                        provider_key_id: providerKeyId,
                    },
                })
            }
        },
        setDates: () => {
            if (props.id !== 'new') {
                actions.loadTagRuns()
            }
        },
    })),

    afterMount(({ actions, props }) => {
        if (props.id !== 'new') {
            actions.loadTagger()
            actions.loadTagRuns()
        }
        // Read initial tab from URL search params
        const { searchParams } = router.values
        if (searchParams.tab === 'configuration' || searchParams.tab === 'runs') {
            actions.setActiveTab(searchParams.tab)
        }
    }),
])
