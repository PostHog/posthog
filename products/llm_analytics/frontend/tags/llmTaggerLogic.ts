import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { parseTrialProviderKeyId } from '../ModelPicker'
import { LLMProviderKey, llmProviderKeysLogic } from '../settings/llmProviderKeysLogic'
import type { llmTaggerLogicType } from './llmTaggerLogicType'
import { ModelConfiguration, Tagger, TaggerConditionSet, TaggerConfig } from './types'

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
    tagger_config: TaggerConfig
    conditions: TaggerConditionSet[]
    model_configuration: ModelConfiguration | null
}

const DEFAULT_FORM: TaggerForm = {
    name: '',
    description: '',
    enabled: false,
    tagger_config: DEFAULT_TAGGER_CONFIG,
    conditions: [DEFAULT_CONDITION],
    model_configuration: null,
}

export const llmTaggerLogic = kea<llmTaggerLogicType>([
    path(['products', 'llm_analytics', 'taggers', 'llmTaggerLogic']),
    props({} as LLMTaggerLogicProps),
    key((props) => props.id),

    connect(() => ({
        values: [llmProviderKeysLogic, ['providerKeys']],
        actions: [llmProviderKeysLogic, ['loadProviderKeys']],
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
    }),

    selectors({
        isNewTagger: [(_, props) => [props.id], (id: string) => id === 'new'],
    }),

    forms(({ props }) => ({
        taggerForm: {
            defaults: DEFAULT_FORM,
            errors: (values: TaggerForm) => ({
                name: !values.name ? 'Name is required' : undefined,
                tagger_config: {
                    prompt: !values.tagger_config.prompt ? 'Prompt is required' : undefined,
                    tags:
                        values.tagger_config.tags.length === 0
                            ? 'At least one tag is required'
                            : values.tagger_config.tags.some((t) => !t.name.trim())
                              ? 'All tags must have a name'
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
                    await api.create('api/environments/@current/taggers/', payload)
                    lemonToast.success('Tagger created')
                } else {
                    await api.update(`api/environments/@current/taggers/${props.id}/`, payload)
                    lemonToast.success('Tagger updated')
                }
                router.actions.push(urls.llmAnalyticsTags())
            },
        },
    })),

    listeners(({ props, actions, values }) => ({
        loadTagger: async () => {
            if (props.id === 'new') {
                return
            }
            const tagger = await api.get(`api/environments/@current/taggers/${props.id}/`)
            actions.loadTaggerSuccess(tagger)
            actions.setTaggerFormValues({
                name: tagger.name,
                description: tagger.description || '',
                enabled: tagger.enabled,
                tagger_config: tagger.tagger_config,
                conditions: tagger.conditions.length > 0 ? tagger.conditions : [DEFAULT_CONDITION],
                model_configuration: tagger.model_configuration,
            })
        },
        deleteTagger: async () => {
            if (props.id === 'new') {
                return
            }
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
    })),

    afterMount(({ actions, props }) => {
        if (props.id !== 'new') {
            actions.loadTagger()
        }
    }),
])
