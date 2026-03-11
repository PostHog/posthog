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
    bytecode?: unknown[]
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
    trace_id?: string | null
    input_preview: string
    output_preview: string
    result: boolean | null
    reasoning: string
    error: string | null
}

export type EvaluationReportFrequency = 'hourly' | 'daily' | 'weekly'

export interface EvaluationReportDeliveryTarget {
    type: 'email' | 'slack'
    value?: string
    integration_id?: number
    channel?: string
}

export interface EvaluationReport {
    id: string
    evaluation: string
    frequency: EvaluationReportFrequency
    byweekday: string[] | null
    start_date: string
    next_delivery_date: string | null
    delivery_targets: EvaluationReportDeliveryTarget[]
    max_sample_size: number
    enabled: boolean
    deleted: boolean
    last_delivered_at: string | null
    created_by: number | null
    created_at: string
}

export interface EvaluationReportSection {
    content: string
    referenced_generation_ids: string[]
}

export interface EvaluationReportRunContent {
    executive_summary?: EvaluationReportSection
    statistics?: EvaluationReportSection
    trend_analysis?: EvaluationReportSection
    failure_patterns?: EvaluationReportSection
    pass_patterns?: EvaluationReportSection
    notable_changes?: EvaluationReportSection
    recommendations?: EvaluationReportSection
    risk_assessment?: EvaluationReportSection
}

export interface EvaluationReportRunMetadata {
    total_runs: number
    pass_count: number
    fail_count: number
    na_count: number
    pass_rate: number
    previous_pass_rate: number | null
}

export interface EvaluationReportRun {
    id: string
    report: string
    content: EvaluationReportRunContent
    metadata: EvaluationReportRunMetadata
    period_start: string
    period_end: string
    delivery_status: 'pending' | 'delivered' | 'partial_failure' | 'failed'
    delivery_errors: string[]
    created_at: string
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
