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
    /** Optional per-report custom guidance appended to the agent's system prompt. */
    report_prompt_guidance: string
    created_by: number | null
    created_at: string
}

/** A titled markdown section of the report (v2: agent-chosen title). */
export interface EvaluationReportSection {
    title: string
    content: string
}

/** A trace reference cited by the agent to ground a specific finding. */
export interface EvaluationReportCitation {
    generation_id: string
    trace_id: string
    reason: string
}

/** Structured metrics computed mechanically from ClickHouse (agent cannot fabricate). */
export interface EvaluationReportMetrics {
    total_runs: number
    pass_count: number
    fail_count: number
    na_count: number
    pass_rate: number
    period_start: string
    period_end: string
    previous_total_runs: number | null
    previous_pass_rate: number | null
}

/** Top-level report content stored in EvaluationReportRun.content. */
export interface EvaluationReportRunContent {
    title: string
    sections: EvaluationReportSection[]
    citations: EvaluationReportCitation[]
    metrics: EvaluationReportMetrics
}

export interface EvaluationReportRun {
    id: string
    report: string
    content: EvaluationReportRunContent
    /** Legacy mirror of content.metrics — populated by the store activity for backwards compat. */
    metadata: EvaluationReportMetrics
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
