import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { ArtifactLinkDTOApi } from 'products/subscriptions/frontend/generated/api.schemas'

const ARTIFACT_STATUS: Record<string, string> = {
    reserved: 'Reserved',
    creating: 'In progress',
    verified: 'Prepared',
    failed: 'Failed',
    publication_unknown: 'Publication status unknown',
}

const EXTERNAL_STATE: Record<string, string> = {
    open: 'Draft PR is open.',
    publication_unknown: 'Draft PR publication status is unknown.',
}

function pullRequestUrl(value: string | null): string | null {
    if (!value) {
        return null
    }
    try {
        const url = new URL(value)
        const parts = url.pathname.split('/').filter(Boolean)
        return url.protocol === 'https:' &&
            url.hostname === 'github.com' &&
            !url.search &&
            !url.hash &&
            parts.length === 4 &&
            parts[2] === 'pull' &&
            /^[1-9]\d*$/.test(parts[3])
            ? value
            : null
    } catch {
        return null
    }
}

function artifactStateLabel(artifact: ArtifactLinkDTOApi): string {
    if (artifact.external_state === 'merged') {
        return 'Merged'
    }
    if (artifact.external_state === 'closed') {
        return 'Closed'
    }
    return ARTIFACT_STATUS[artifact.status] ?? 'Unavailable'
}

export function SubscriptionPulseArtifacts({
    artifacts,
    linkLabel,
}: {
    artifacts: ArtifactLinkDTOApi[]
    linkLabel?: string
}): JSX.Element | null {
    if (artifacts.length === 0) {
        return null
    }
    return (
        <div className="flex flex-wrap items-center gap-2">
            {artifacts.map((artifact, index) => {
                const pullRequest = pullRequestUrl(artifact.external_url)
                const label = linkLabel ?? (artifact.kind === 'experiment_draft' ? 'Experiment draft' : 'Draft PR')
                return (
                    <div
                        key={`${artifact.kind}-${artifact.task_id ?? artifact.experiment_id ?? index}`}
                        className="flex flex-wrap items-center gap-2"
                    >
                        <LemonTag type="default">{artifactStateLabel(artifact)}</LemonTag>
                        {artifact.external_state && EXTERNAL_STATE[artifact.external_state] ? (
                            <span className="text-secondary text-xs">{EXTERNAL_STATE[artifact.external_state]}</span>
                        ) : null}
                        {pullRequest ? (
                            <LemonButton type="tertiary" size="xsmall" to={pullRequest} targetBlank>
                                {label}
                            </LemonButton>
                        ) : null}
                        {artifact.experiment_id ? (
                            <LemonButton type="tertiary" size="xsmall" to={urls.experiment(artifact.experiment_id)}>
                                {label}
                            </LemonButton>
                        ) : null}
                        {artifact.task_id ? (
                            <LemonButton type="tertiary" size="xsmall" to={urls.taskDetail(artifact.task_id)}>
                                View task
                            </LemonButton>
                        ) : null}
                    </div>
                )
            })}
        </div>
    )
}
