import clsx from 'clsx'

import { IconPullRequest } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { PRBrowserItemApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReportStatus } from '../../types'
import { SignalReportStatusBadge } from '../badges/SignalReportStatusBadge'

export function pullRequestStateLabel(pr: Pick<PRBrowserItemApi, 'state' | 'draft'>): string {
    if (pr.draft && pr.state === 'open') {
        return 'Draft'
    }
    if (pr.state === 'merged') {
        return 'Merged'
    }
    if (pr.state === 'closed') {
        return 'Closed'
    }
    return 'Open'
}

export function pullRequestStateColor(pr: Pick<PRBrowserItemApi, 'state' | 'draft'>): string {
    if (pr.draft && pr.state === 'open') {
        return 'text-tertiary'
    }
    if (pr.state === 'merged') {
        return 'text-purple'
    }
    if (pr.state === 'closed') {
        return 'text-danger'
    }
    return 'text-success'
}

export function PullRequestRow({ pr, onSelect }: { pr: PRBrowserItemApi; onSelect: () => void }): JSX.Element {
    const stateLabel = pullRequestStateLabel(pr)
    return (
        <button
            type="button"
            data-attr="inbox-pr-row"
            onClick={onSelect}
            className="group flex w-full min-w-0 cursor-pointer items-start gap-2.5 border-b border-primary px-3 py-2 text-left transition-colors hover:bg-fill-highlight-50 focus-visible:bg-fill-highlight-50 focus-visible:outline-none"
        >
            <Tooltip title={`${stateLabel} pull request`} placement="left">
                <span className={clsx('mt-0.5 flex shrink-0 items-center', pullRequestStateColor(pr))}>
                    <IconPullRequest className="size-3.5" />
                </span>
            </Tooltip>
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <div className="flex items-start justify-between gap-2">
                    <span className="min-w-0 flex-1 line-clamp-2 break-words text-[13px] font-medium leading-snug text-primary">
                        {pr.title}
                    </span>
                    {pr.report ? (
                        <span className="shrink-0">
                            <SignalReportStatusBadge status={pr.report.status as SignalReportStatus} />
                        </span>
                    ) : pr.state !== 'closed' ? (
                        <span className="shrink-0 text-[11px] font-medium text-tertiary opacity-0 transition-opacity group-hover:opacity-100">
                            Monitor →
                        </span>
                    ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-tertiary">
                    <span className="truncate font-mono">
                        {pr.repository}#{pr.number}
                    </span>
                    <span>·</span>
                    <span>{stateLabel}</span>
                    <span>·</span>
                    <TZLabel time={pr.created_at} />
                </div>
            </div>
        </button>
    )
}
