import { AnyPropertyFilter } from '~/types'

export interface EvaluationConfig {
    id: string
    name: string
    description?: string
    enabled: boolean
    evaluation_type: 'llm_judge'
    evaluation_config: {
        prompt: string
    }
    output_type: 'boolean'
    output_config: Record<string, never>
    conditions: EvaluationConditionSet[]
    total_runs: number
    last_run_at?: string
    created_at: string
    updated_at: string
    deleted?: boolean
}

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
    result: boolean
    reasoning: string
    status: 'completed' | 'failed' | 'running'
}
