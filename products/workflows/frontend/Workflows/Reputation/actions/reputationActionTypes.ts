export type ReputationActionSeverity = 'high' | 'medium' | 'low'

// pinned: part of the data-attr on each action's buttons, which autocapture dashboards read
export type ReputationActionKind =
    | 'project-suspended'
    | 'provider-status'
    | 'paused-workflow'
    | 'finding'
    | 'project-rate'
    | 'workflow-rate'
    | 'provider-rate'

export type ReputationBreakdownTab = 'workflows' | 'providers'

export type ReputationSetupTab = 'channels' | 'opt-outs'

export interface ReputationPageControls {
    openSupportForm: (message: string) => void
    showBreakdown: (tab: ReputationBreakdownTab) => void
}

export type ReputationActionCta =
    | { label: string; to: string }
    | { label: string; onClick: (page: ReputationPageControls) => void }

export interface ReputationDocsLink {
    label: string
    to: string
}

export interface ReputationAction {
    key: string
    kind: ReputationActionKind
    severity: ReputationActionSeverity
    /** True when no email goes out until the user acts. Only these items use the danger color. */
    blocksSending: boolean
    title: string
    description: string
    /** Missing when no page in PostHog helps with the item. */
    cta?: ReputationActionCta
    docsLink?: ReputationDocsLink
}
