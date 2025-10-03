import { AnyPropertyFilter } from '~/types'

export interface EvaluationConfig {
    id: string
    name: string
    description?: string
    enabled: boolean
    prompt: string
    conditions: EvaluationConditionSet[]
    total_runs: number
    last_run_at?: string
    created_at: string
    updated_at: string
}

export interface EvaluationConditionSet {
    id: string
    rollout_percentage: number
    properties: AnyPropertyFilter[]
}

export interface EvaluationRun {
    id: string
    evaluation_id: string
    generation_id: string
    timestamp: string
    input_preview: string
    output_preview: string
    result: boolean
    status: 'completed' | 'failed' | 'running'
    error_message?: string
}
