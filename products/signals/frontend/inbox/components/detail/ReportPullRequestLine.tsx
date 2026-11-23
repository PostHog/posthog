import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'

import { parsePrUrlParts, safeHttpUrl } from '../../utils/reportPresentation'
import { ReportPullRequest } from '../../utils/reportPullRequests'

const PULL_REQUEST_STATES: Record<ReportPullRequest['state'], string> = {
    unknown: 'Status unavailable',
    draft: 'Draft',
    open: 'Open',
    closed: 'Closed',
    merged: 'Merged',
}

const REVIEW_DECISIONS: Record<NonNullable<ReportPullRequest['review_decision']>, string> = {
    approved: 'Approved',
    changes_requested: 'Changes requested',
    review_required: 'Review required',
}

function PullRequestState({ pullRequest }: { pullRequest: ReportPullRequest }): JSX.Element {
    const state = PULL_REQUEST_STATES[pullRequest.state] ?? PULL_REQUEST_STATES.unknown
    const isOpen = pullRequest.state === 'open' || pullRequest.state === 'draft'
    if (isOpen && pullRequest.review_decision) {
        return <span className="truncate">{`${state} · ${REVIEW_DECISIONS[pullRequest.review_decision]}`}</span>
    }
    if (pullRequest.state === 'merged' && pullRequest.merged_at) {
        return (
            <span className="flex items-center gap-1 truncate">
                <span>{state}</span>
                <TZLabel time={pullRequest.merged_at} formatDate="D MMM" formatTime="" timestampStyle="absolute" />
            </span>
        )
    }
    return <span className="truncate">{state}</span>
}

/**
 * One pull request of the report as a single line: the number links to GitHub, the rest of the line
 * selects the pull request for Files changed, CI checks and Comments when `onSelect` is set.
 */
export function ReportPullRequestLine({
    pullRequest,
    reportRepository,
    selected = false,
    onSelect,
}: {
    pullRequest: ReportPullRequest
    /** The repository prefix is left out for a pull request in this repository. */
    reportRepository: string | null | undefined
    selected?: boolean
    onSelect?: () => void
}): JSX.Element {
    const prUrl = safeHttpUrl(pullRequest.url)
    const prRef = prUrl ? parsePrUrlParts(prUrl) : null
    const label = prRef
        ? prRef.repoSlug.toLowerCase() === reportRepository?.toLowerCase()
            ? `#${prRef.number}`
            : `${prRef.repoSlug}#${prRef.number}`
        : null

    return (
        <li
            className={cn(
                '-mx-1 flex min-h-6 min-w-0 items-center gap-2 rounded px-1',
                selected && 'bg-fill-highlight-100'
            )}
            aria-current={selected || undefined}
        >
            {label && prUrl ? (
                <Link to={prUrl} target="_blank" className="min-w-0 truncate">
                    {label}
                </Link>
            ) : (
                <span className="shrink-0 text-tertiary">Unavailable</span>
            )}
            {onSelect ? (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    noPadding
                    onClick={onSelect}
                    aria-pressed={selected}
                    aria-label={label ? `Show ${label} in this report` : 'Show this pull request in this report'}
                    tooltip="Show this pull request's files, checks and comments"
                    data-attr="inbox-report-select-pull-request"
                    className="grow shrink-0 font-normal"
                >
                    <span className="ml-auto flex min-w-0 text-xs font-normal text-default">
                        <PullRequestState pullRequest={pullRequest} />
                    </span>
                </LemonButton>
            ) : (
                <span className="ml-auto flex min-w-0 shrink-0 justify-end text-right">
                    <PullRequestState pullRequest={pullRequest} />
                </span>
            )}
        </li>
    )
}
