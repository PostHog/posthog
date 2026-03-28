import { AnyPropertyFilter } from '~/types'

import { LLMProvider } from '../settings/llmProviderKeysLogic'

export interface TagDefinition {
    name: string
    description?: string
}

export interface TaggerConfig {
    prompt: string
    tags: TagDefinition[]
    min_tags: number
    max_tags: number | null
}

export interface ModelConfiguration {
    provider: LLMProvider
    model: string
    provider_key_id: string | null
    provider_key_name?: string | null
}

export interface TaggerConditionSet {
    id: string
    rollout_percentage: number
    properties: AnyPropertyFilter[]
}

export interface Tagger {
    id: string
    name: string
    description?: string
    enabled: boolean
    tagger_config: TaggerConfig
    conditions: TaggerConditionSet[]
    model_configuration: ModelConfiguration | null
    created_at: string
    updated_at: string
    deleted?: boolean
}
