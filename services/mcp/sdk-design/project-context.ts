export interface ProjectContext {
    projectId: number
    /** Available when resolution supplied the organization; explicit IDs need no extra lookup. */
    organizationId?: string
    source: 'explicit' | 'environment' | 'token_scope' | 'user_selection'
}

export interface ProjectResolutionErrorDetails {
    reason: 'ambiguous' | 'missing' | 'discovery_unavailable'
    /** Known token-scoped candidates; an empty list does not establish that the user has no projects. */
    candidateProjectIds: number[]
}
