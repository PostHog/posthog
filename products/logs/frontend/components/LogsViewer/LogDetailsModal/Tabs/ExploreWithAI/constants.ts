import { ActionPriority, ConfidenceLevel, SeverityAssessment } from './types'

export const SEVERITY_CONFIG: Record<
    SeverityAssessment,
    { banner: 'info' | 'warning' | 'error' | 'success'; label: string }
> = {
    ok: { banner: 'success', label: 'Likely not an issue' },
    warning: { banner: 'warning', label: 'May need attention' },
    error: { banner: 'error', label: 'Likely an issue' },
    critical: { banner: 'error', label: 'Likely critical' },
}

export const CONFIDENCE_CONFIG: Record<ConfidenceLevel, { type: 'danger' | 'warning' | 'success'; label: string }> = {
    high: { type: 'success', label: 'High confidence' },
    medium: { type: 'warning', label: 'Medium confidence' },
    low: { type: 'danger', label: 'Low confidence' },
}

export const PRIORITY_TAG_TYPE: Record<ActionPriority, 'highlight' | 'option' | 'muted'> = {
    now: 'highlight',
    soon: 'option',
    later: 'muted',
}

export const PRIORITY_TOOLTIP: Record<ActionPriority, string> = {
    now: 'AI suggests: do immediately',
    soon: 'AI suggests: address soon',
    later: 'AI suggests: can wait',
}
