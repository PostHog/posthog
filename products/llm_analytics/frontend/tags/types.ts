import { AnyPropertyFilter } from '~/types'

import { LLMProvider } from '../settings/llmProviderKeysLogic'

export interface TagDefinition {
    name: string
    description?: string
}

export type TaggerType = 'llm' | 'hog'

export interface LLMTaggerConfig {
    prompt: string
    tags: TagDefinition[]
    min_tags: number
    max_tags: number | null
}

export interface HogTaggerConfig {
    source: string
    bytecode?: unknown[]
    tags: TagDefinition[]
}

export type TaggerConfig = LLMTaggerConfig | HogTaggerConfig

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
    tagger_type: TaggerType
    tagger_config: TaggerConfig
    conditions: TaggerConditionSet[]
    model_configuration: ModelConfiguration | null
    created_at: string
    updated_at: string
    deleted?: boolean
}
