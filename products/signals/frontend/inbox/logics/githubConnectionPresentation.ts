import type { SignalTeamConfigApi } from '../../generated/api.schemas'

export interface GitHubConnectionPresentation {
    title: string
    description: string
    action: string
    blocked: boolean
    retry: boolean
}

export function githubConnectionPresentation(
    config: Partial<SignalTeamConfigApi> | null
): GitHubConnectionPresentation | null {
    const readiness = config?.github_readiness
    if (!readiness || readiness === 'ready' || !config?.research_access) {
        return null
    }
    const blocked = config.research_access.mode === 'blocked'
    const retry = readiness === 'temporarily_unavailable'
    const action = {
        not_connected: 'Connect GitHub',
        reconnect_required: 'Reconnect GitHub',
        no_repositories: 'Grant repository access',
        temporarily_unavailable: 'Retry GitHub check',
    }[readiness]
    return {
        title: blocked ? 'Self-driving is paused' : 'Research continues without code',
        description: blocked
            ? retry
                ? 'GitHub access is temporarily unavailable. Research will retry when access is available.'
                : 'Restore project access to a GitHub repository to resume research and scouts.'
            : 'Self-driving can research your project data. Implementation needs a verified repository and your existing permissions.',
        action,
        blocked,
        retry,
    }
}
