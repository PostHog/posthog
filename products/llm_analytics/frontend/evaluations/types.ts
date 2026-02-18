import { AnyPropertyFilter } from '~/types'

import { LLMProvider } from '../settings/llmProviderKeysLogic'

export type EvaluationType = 'llm_judge' | 'hog'
export type EvaluationOutputType = 'boolean'

export interface ModelConfiguration {
    provider: LLMProvider
    model: string
    provider_key_id: string | null
    provider_key_name?: string | null
}

export interface EvaluationOutputConfig {
    allows_na?: boolean
}

export interface LLMJudgeEvaluationConfig {
    prompt: string
}

export interface HogEvaluationConfig {
    source: string
    bytecode?: any[]
}

export interface BaseEvaluationConfig {
    id: string
    name: string
    description?: string
    enabled: boolean
    output_type: EvaluationOutputType
    output_config: EvaluationOutputConfig
    conditions: EvaluationConditionSet[]
    model_configuration: ModelConfiguration | null
    total_runs: number
    last_run_at?: string
    created_at: string
    updated_at: string
    deleted?: boolean
}

export interface LLMJudgeEvaluation extends BaseEvaluationConfig {
    evaluation_type: 'llm_judge'
    evaluation_config: LLMJudgeEvaluationConfig
}

export interface HogEvaluation extends BaseEvaluationConfig {
    evaluation_type: 'hog'
    evaluation_config: HogEvaluationConfig
}

export type EvaluationConfig = LLMJudgeEvaluation | HogEvaluation

export interface EvaluationConditionSet {
    id: string
    rollout_percentage: number
    properties: AnyPropertyFilter[]
}

export interface EvaluationRun {
    id: string
    evaluation_id: string
    evaluation_name: string
    generation_id: string
    trace_id: string
    timestamp: string
    result: boolean | null
    applicable?: boolean
    reasoning: string
    status: 'completed' | 'failed' | 'running'
}

export interface HogTestResult {
    event_uuid: string
    input_preview: string
    output_preview: string
    result: boolean | null
    reasoning: string
    error: string | null
}

export type EvaluationSummaryFilter = 'all' | 'pass' | 'fail' | 'na'

export interface EvaluationPattern {
    title: string
    description: string
    frequency: string
    example_generation_ids: string[]
}

export interface EvaluationSummaryStatistics {
    total_analyzed: number
    pass_count: number
    fail_count: number
    na_count: number
}

export interface EvaluationSummary {
    overall_assessment: string
    pass_patterns: EvaluationPattern[]
    fail_patterns: EvaluationPattern[]
    na_patterns: EvaluationPattern[]
    recommendations: string[]
    statistics: EvaluationSummaryStatistics
}
