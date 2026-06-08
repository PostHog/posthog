export type PulseDigestStatus = 'pending' | 'generating' | 'delivered' | 'failed'
export type PulseSubscriptionFrequency = 'weekly' | 'daily'
export type PulseDetectionMode = 'change_v1' | 'discovery'
export type PulseSensitivity = 'conservative' | 'balanced' | 'sensitive' | 'custom'

export interface PulseDigestSummary {
    id: string
    period_start: string
    period_end: string
    status: PulseDigestStatus
    error: Record<string, any> | null
    created_at: string
    finding_count: number
    summary: string
}

// A same-period change (feature flag, experiment, annotation) the finding's narrative tied to it. Carries
// its own ISO timestamp so it can be placed on the finding's timeline; the deep link is built from (type, id).
export interface PulseReference {
    type: 'feature_flag' | 'experiment' | 'annotation' | string
    label: string
    timestamp?: string // full ISO instant
    id?: string
    change?: string // 'turned on', 'launched', etc. (flags/experiments; absent for annotations)
}

export interface PulseFindingType {
    id: string
    digest: string
    metric_label: string
    metric_descriptor: Record<string, any>
    current_value: number
    baseline_value: number
    change_pct: number
    robust_z: number
    impact: number
    attribution_breakdown: Record<string, any> | null
    evidence: {
        series?: number[] // weekly values (detection baseline window + current)
        daily_series?: number[] // daily values over the digest period — drives the finding chart when present
        session_ids?: string[]
        references?: PulseReference[]
    } | null
    narrative: string
    chart_thumbnail_url: string
    rank: number
    created_at: string
}

export interface PulseDigestDetail extends PulseDigestSummary {
    workflow_run_id: string
    findings: PulseFindingType[]
}

// A positioned marker on a finding's timeline: one change the finding's narrative referenced, placed by
// time along the digest period (0..1) with a deep link to the flag / experiment / annotation.
export interface PulseTimelineMarker {
    key: string
    type: PulseReference['type']
    label: string
    change?: string
    timestamp: string // full ISO
    position: number // 0..1 along period_start..period_end
    to?: string // deep link to the flag / experiment / annotation
}

export interface PulseSubscriptionType {
    id: string | null
    enabled: boolean
    frequency: PulseSubscriptionFrequency
    detection_mode: PulseDetectionMode
    sensitivity: PulseSensitivity
    min_change_pct: number
    baseline_weeks: number
    max_findings: number
    robust_z_threshold: number
    last_scan_at: string | null
    next_scan_at: string | null
    created_at: string | null
}

export interface PulseWatchedCandidate {
    source: string
    source_id: string | null
    label: string
    query: Record<string, any>
}
