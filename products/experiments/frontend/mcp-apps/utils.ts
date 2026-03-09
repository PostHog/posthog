export interface ExperimentVariant {
    key: string
    name?: string
    rollout_percentage?: number
}

export interface ExperimentMetric {
    kind: string
    event?: string
    property?: string
    math?: string
}

export interface ExperimentData {
    id: number
    name: string
    type?: string
    description?: string | null
    feature_flag_key?: string
    start_date?: string | null
    end_date?: string | null
    archived?: boolean
    created_at?: string
    updated_at?: string
    parameters?: {
        feature_flag_variants?: ExperimentVariant[]
        [key: string]: unknown
    }
    metrics?: ExperimentMetric[]
    metrics_secondary?: ExperimentMetric[]
    filters?: Record<string, unknown>
    conclusion?: string | null
    conclusion_comment?: string | null
    _posthogUrl?: string
}

export function getStatus(exp: ExperimentData): { label: string; variant: 'success' | 'warning' | 'neutral' | 'info' } {
    if (exp.archived) {
        return { label: 'Archived', variant: 'neutral' }
    }
    if (!exp.start_date) {
        return { label: 'Draft', variant: 'neutral' }
    }
    if (exp.end_date) {
        return { label: 'Complete', variant: 'success' }
    }
    return { label: 'Running', variant: 'info' }
}
