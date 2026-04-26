// PostHog API response types. Keep in sync with:
//   - frontend/src/queries/schema/schema-general.ts (WebOverviewItem)
//   - posthog/api/feature_flag.py / posthog/api/experiment.py

// -- Feature flags --

export interface PostHogFlagProperty {
    key: string
    value?: string | number | boolean | Array<string | number>
    operator?: string
    type?: 'event' | 'person' | 'group' | 'cohort' | 'element' | 'hogql' | 'session' | 'behavioral'
    negation?: boolean
}

export interface PostHogFlagGroup {
    properties?: PostHogFlagProperty[]
    rollout_percentage?: number | null
    variant?: string | null
}

export interface PostHogFlagVariant {
    key: string
    name?: string
    rollout_percentage: number
}

export interface PostHogFeatureFlag {
    id: number
    key: string
    name: string
    active: boolean
    deleted: boolean
    rollout_percentage: number | null
    filters?: {
        groups?: PostHogFlagGroup[]
        multivariate?: { variants: PostHogFlagVariant[] } | null
        payloads?: Record<string, unknown>
        aggregation_group_type_index?: number
    }
    created_at: string
    updated_at: string
    status: string
    tags: string[]
    experiment_set: number[]
}

// -- Experiments --

export interface PostHogExperiment {
    id: number
    name: string
    description: string | null
    start_date: string | null
    end_date: string | null
    feature_flag_key: string
    archived: boolean
    created_at: string
    updated_at: string
    parameters?: {
        recommended_sample_size?: number
        minimum_detectable_effect?: number
    }
}

// -- Customer journeys --

export interface PostHogCustomerJourney {
    id: string
    insight: number
    name: string
    description: string | null
    created_at: string
    updated_at: string | null
}

// -- Insights / Funnels --

export interface FunnelStepResult {
    action_id: string
    name: string
    custom_name?: string | null
    order: number
    count: number
}

export interface PostHogInsight {
    id: number
    name: string | null
    result?: FunnelStepResult[] | null
    query?: {
        kind?: string
        source?: {
            kind?: string
            series?: Array<{
                kind?: string
                event?: string
                name?: string
                custom_name?: string
            }>
            [key: string]: unknown
        }
        [key: string]: unknown
    }
}

// -- Web analytics --

export interface WebOverviewItem {
    key: string
    value?: number
    previous?: number
    kind: 'unit' | 'duration_s' | 'percentage' | 'currency'
    changeFromPreviousPct?: number
    isIncreaseBad?: boolean
}

// -- Generic --

export interface ListResponse<T> {
    count?: number
    next?: string | null
    previous?: string | null
    results: T[]
}
