import { IconPullRequest } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import type { SignalReportPullRequestApi } from 'products/signals/frontend/generated/api.schemas'

import { parsePrUrlParts } from '../../utils/reportPresentation'

interface ArtefactPullRequestProps {
    url: string
    implementationTitle?: string
    state?: SignalReportPullRequestApi['state']
    outcome?: 'closed' | 'already_closed' | 'skipped'
}

export function ArtefactPullRequest({
    url,
    implementationTitle,
    state,
    outcome,
}: ArtefactPullRequestProps): JSX.Element {
    const pr = parsePrUrlParts(url)
    const title = implementationTitle?.replace(/^Implementation:\s*/i, '').trim()
    const status = state ?? 'unknown'
    const label = { unknown: 'Status unavailable', draft: 'Draft', open: 'Open', closed: 'Closed', merged: 'Merged' }[
        status
    ]

    return (
        <div className="min-w-0 space-y-1.5" data-attr="inbox-activity-pull-request">
            <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-xs text-secondary">
                <IconPullRequest className="shrink-0" />
                <span className="break-all">{pr ? `${pr.repoSlug} · #${pr.number}` : 'Pull request'}</span>
                <LemonTag size="small" type={status === 'open' ? 'success' : status === 'merged' ? 'primary' : 'muted'}>
                    {label}
                </LemonTag>
            </div>
            <Link
                to={url}
                target="_blank"
                className="block min-w-0 break-words [overflow-wrap:anywhere] text-sm font-medium"
                data-attr="inbox-activity-pull-request-link"
                title={implementationTitle ? 'Implementation task title' : undefined}
            >
                {title || (pr ? `Pull request #${pr.number}` : url)}
            </Link>
            {outcome ? (
                <span className="block text-xs text-secondary">
                    {outcome === 'skipped'
                        ? 'Not closed by PostHog'
                        : outcome === 'already_closed'
                          ? 'Already closed at replacement'
                          : 'Closed by PostHog'}
                </span>
            ) : null}
        </div>
    )
}
