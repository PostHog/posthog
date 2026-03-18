export type SeverityAssessment = 'ok' | 'warning' | 'error' | 'critical'
export type ConfidenceLevel = 'high' | 'medium' | 'low'
export type ActionPriority = 'now' | 'soon' | 'later'

export interface ProbableCause {
    hypothesis: string
    confidence: ConfidenceLevel
    reasoning: string
}

export interface ImmediateAction {
    action: string
    priority: ActionPriority
    why: string
}

export interface KeyField {
    field: string
    value: string
    significance: string
    attribute_type: 'log' | 'resource'
}

export interface LogExplanation {
    headline: string
    severity_assessment: SeverityAssessment
    impact_summary: string
    probable_causes: ProbableCause[]
    immediate_actions: ImmediateAction[]
    technical_explanation: string
    key_fields: KeyField[]
}
