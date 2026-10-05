export type ReputationActionSeverity = 'high' | 'medium' | 'low'

// pinned: part of the data-attr on each action's buttons, which autocapture dashboards read
export type ReputationActionKind =
    | 'project-suspended'
    | 'provider-status'
    | 'paused-workflow'
    | 'rate-finding'
    | 'dns-finding'
    | 'bimi-finding'
    | 'other-finding'
    | 'project-rate'
    | 'workflow-rate'
    | 'provider-rate'

export type ReputationBreakdownTab = 'workflows' | 'providers'

export type ReputationSetupTab = 'channels' | 'opt-outs'

export interface ReputationPageControls {
    openSupportForm: (message: string) => void
    showBreakdown: (tab: ReputationBreakdownTab) => void
}

// The `never` members stop a button from declaring both a link and a click handler.
export type ReputationActionCta =
    | { label: string; to: string; onClick?: never }
    | { label: string; onClick: (page: ReputationPageControls) => void; to?: never }

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
    cta?: ReputationActionCta
    docsLink?: ReputationDocsLink
}
