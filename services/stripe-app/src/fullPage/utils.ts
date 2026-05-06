import type { PostHogExperiment, PostHogFeatureFlag, PostHogFlagProperty } from '../posthog/types'

export type FlagStatus = 'enabled' | 'disabled' | 'beta'

export type ExperimentStatus = 'running' | 'complete' | 'draft'

export function flagStatusOf(flag: PostHogFeatureFlag): FlagStatus {
    if (!flag.active) {
        return 'disabled'
    }
    const rollout = flag.rollout_percentage ?? flag.filters?.groups?.[0]?.rollout_percentage ?? null
    if (rollout !== null && rollout < 100) {
        return 'beta'
    }
    return 'enabled'
}

export function experimentStatusOf(experiment: PostHogExperiment): ExperimentStatus {
    if (experiment.end_date) {
        return 'complete'
    }
    if (experiment.start_date) {
        return 'running'
    }
    return 'draft'
}

export function flagBadgeType(status: FlagStatus): 'positive' | 'info' | 'neutral' {
    if (status === 'enabled') {
        return 'positive'
    }
    if (status === 'beta') {
        return 'info'
    }
    return 'neutral'
}

// Render a single PropertyFilter as a human-readable clause, e.g. `email icontains "@posthog.com"`.
export function formatProperty(p: PostHogFlagProperty): string {
    const op = operatorLabel(p.operator)
    const valueStr = formatValue(p.value)
    const negation = p.negation ? 'not ' : ''
    if (p.operator === 'is_set' || p.operator === 'is_not_set') {
        return `${negation}${p.key} ${op}`
    }
    return valueStr ? `${negation}${p.key} ${op} ${valueStr}` : `${negation}${p.key} ${op}`
}

function operatorLabel(op?: string): string {
    switch (op) {
        case undefined:
        case 'exact':
            return '='
        case 'is_not':
            return '!='
        case 'icontains':
            return 'contains'
        case 'not_icontains':
            return 'does not contain'
        case 'regex':
            return 'matches'
        case 'not_regex':
            return 'does not match'
        case 'gt':
            return '>'
        case 'lt':
            return '<'
        case 'gte':
            return '>='
        case 'lte':
            return '<='
        case 'is_set':
            return 'is set'
        case 'is_not_set':
            return 'is not set'
        case 'is_date_before':
            return 'before'
        case 'is_date_after':
            return 'after'
        default:
            return op
    }
}

function formatValue(v: PostHogFlagProperty['value']): string {
    if (v === undefined || v === null) {
        return ''
    }
    if (Array.isArray(v)) {
        return v.map((x: string | number) => JSON.stringify(x)).join(', ')
    }
    if (typeof v === 'string') {
        return JSON.stringify(v)
    }
    return String(v)
}
