export interface ExperimentVariant {
    key: string
    name?: string
    rollout_percentage?: number
    split_percent?: number
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
    feature_flag?: {
        id?: number
        key?: string
        name?: string
        filters?: {
            groups?: { rollout_percentage?: number | null }[]
            multivariate?: {
                variants?: ExperimentVariant[]
            } | null
        } | null
    } | null
    metrics?: ExperimentMetric[]
    metrics_secondary?: ExperimentMetric[]
    filters?: Record<string, unknown>
    conclusion?: string | null
    conclusion_comment?: string | null
    _posthogUrl?: string
}

export type StatusVariant = 'success' | 'warning' | 'default' | 'info'

export function getStatus(exp: ExperimentData): { label: string; variant: StatusVariant } {
    if (exp.archived) {
        return { label: 'Archived', variant: 'default' }
    }
    if (!exp.start_date) {
        return { label: 'Draft', variant: 'default' }
    }
    if (exp.end_date) {
        return { label: 'Complete', variant: 'success' }
    }
    return { label: 'Running', variant: 'info' }
}

export type ConclusionVariant = 'success' | 'destructive' | 'default'

export function getConclusion(exp: ExperimentData): { label: string; variant: ConclusionVariant } {
    if (exp.conclusion === 'won') {
        return { label: 'Won', variant: 'success' }
    }
    if (exp.conclusion === 'lost') {
        return { label: 'Lost', variant: 'destructive' }
    }

    return {
        label: exp.conclusion ? exp.conclusion.charAt(0).toUpperCase() + exp.conclusion.slice(1) : 'Inconclusive',
        variant: 'default',
    }
}
