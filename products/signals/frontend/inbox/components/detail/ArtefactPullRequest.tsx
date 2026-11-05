import { IconPullRequest } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import type { SignalReportPullRequestApi } from 'products/signals/frontend/generated/api.schemas'

import { type ArtefactPullRequestOutcome, artefactPullRequestView } from './artefactLogPresentation'

interface ArtefactPullRequestProps {
    url: string
    implementationTitle?: string
    state?: SignalReportPullRequestApi['state']
    outcome?: ArtefactPullRequestOutcome
}

export function ArtefactPullRequest({
    url,
    implementationTitle,
    state,
    outcome,
}: ArtefactPullRequestProps): JSX.Element {
    const view = artefactPullRequestView({ url, implementationTitle, state, outcome })

    return (
        <div className="min-w-0 space-y-1.5" data-attr="inbox-activity-pull-request">
            <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-xs text-secondary">
                <IconPullRequest className="shrink-0" />
                <span className="break-all">{view.repoLabel}</span>
                <LemonTag size="small" type={view.statusTagType}>
                    {view.statusLabel}
                </LemonTag>
            </div>
            <Link
                to={url}
                target="_blank"
                className="block min-w-0 break-words [overflow-wrap:anywhere] text-sm font-medium"
                data-attr="inbox-activity-pull-request-link"
                title={implementationTitle ? 'Implementation task title' : undefined}
            >
                {view.linkText}
            </Link>
            {view.outcomeLabel ? <span className="block text-xs text-secondary">{view.outcomeLabel}</span> : null}
        </div>
    )
}
