import type { ArtifactLinkDTOApi, RunActionHistoryDTOApi } from 'products/subscriptions/frontend/generated/api.schemas'

const PREPARED_ARTIFACT_STATUSES = new Set(['reserved', 'creating', 'verified', 'publication_unknown'])

const FAILURE_COPY: Record<string, string> = {
    finalization_timeout: 'Pulse timed out before every step finished.',
    pulse_timed_out: 'Pulse timed out before every step finished.',
    proactive_disabled: 'Pulse was disabled by policy for this delivery.',
    overlap_active_run: 'Another Pulse run was already active.',
    team_concurrency_limit: 'Pulse reached this project’s concurrency limit.',
    global_concurrency_limit: 'Pulse reached its concurrency limit.',
    team_daily_limit: 'Pulse reached this project’s daily limit.',
    global_daily_limit: 'Pulse reached its daily limit.',
    publication_blocked: 'Publication was blocked by the safety check.',
    publication_runtime_unsupported: 'Publication was unavailable in this runtime.',
    repository_grant_revoked: 'Repository access was no longer available.',
    gate_policy_unavailable: 'The repository does not provide a usable protected build and test policy.',
    publication_gate_failed: 'The protected build or test checks failed, so Pulse did not publish a draft PR.',
}

export function failureMessage(code: string | null): string | null {
    if (!code) {
        return null
    }
    return FAILURE_COPY[code] ?? 'A Pulse step did not finish.'
}

export function isAdviceAction(action: RunActionHistoryDTOApi): boolean {
    return action.kind === 'recommendation'
}

export function preparedArtifacts(action: RunActionHistoryDTOApi): ArtifactLinkDTOApi[] {
    return action.artifacts.filter((artifact) => PREPARED_ARTIFACT_STATUSES.has(artifact.status))
}

export function failedArtifacts(action: RunActionHistoryDTOApi): ArtifactLinkDTOApi[] {
    return action.artifacts.filter((artifact) => artifact.status === 'failed')
}

export function isPreparationFailure(action: RunActionHistoryDTOApi): boolean {
    return !isAdviceAction(action) && (action.status === 'failed' || failedArtifacts(action).length > 0)
}

export function isUnpreparedAction(action: RunActionHistoryDTOApi): boolean {
    return !isAdviceAction(action) && preparedArtifacts(action).length === 0
}

export function actionStatusLabel(status: string): string {
    return (
        {
            proposed: 'recommended',
            selected: 'selected',
            executing: 'in progress',
            completed: 'completed',
            failed: 'failed',
            skipped: 'skipped',
        }[status] ?? 'unknown'
    )
}
