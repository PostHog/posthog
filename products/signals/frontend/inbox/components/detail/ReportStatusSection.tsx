import { type ReactNode } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Link } from 'lib/lemon-ui/Link'

import type { ReportPriorityApi } from 'products/signals/frontend/generated/api.schemas'

import { PRIORITY_MEANING, PRIORITY_TAG_TYPE } from '../../filterOptions'
import { SignalReport } from '../../types'
import { parsePrUrlParts, safeHttpUrl } from '../../utils/reportPresentation'
import { ReportPullRequest, reportPullRequests } from '../../utils/reportPullRequests'
import { STATUS_LABELS } from '../badges/SignalReportStatusBadge'
import { DetailSection } from './DetailSection'

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

function StatusRow({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <div className="flex min-h-6 items-center justify-between gap-3">
            <dt className="text-xs text-secondary">{label}</dt>
            <dd className="m-0 flex min-w-0 flex-wrap items-center justify-end gap-1.5 text-right text-xs">
                {children}
            </dd>
        </div>
    )
}

function externalClaimLabel(report: SignalReport): string | null {
    const assignee = report.assignee
    if (assignee?.kind !== 'agent') {
        return null
    }
    return assignee.agent?.trim() || 'External agent'
}

export function ReportStatusSection({
    report,
    rightSlot,
    onPriorityChange,
    prioritySaving = false,
}: {
    report: SignalReport
    rightSlot?: ReactNode
    onPriorityChange?: (priority: ReportPriorityApi) => void
    prioritySaving?: boolean
}): JSX.Element {
    const externalClaim = externalClaimLabel(report)
    const pullRequests = reportPullRequests(report)
    const trackerUrl = safeHttpUrl(report.tracker_issue_url ?? '')

    return (
        <DetailSection icon={<IconInfo />} title="Status" rightSlot={rightSlot} collapsible>
            <dl className="m-0 flex flex-col gap-2">
                <StatusRow label="Report status">{STATUS_LABELS[report.status] ?? report.status}</StatusRow>
                {externalClaim && <StatusRow label="In progress by">{externalClaim}</StatusRow>}
                {report.priority && (
                    <StatusRow label="Priority">
                        {onPriorityChange ? (
                            <LemonSelect<ReportPriorityApi>
                                aria-label="Change report priority"
                                data-attr="report-priority-select"
                                value={report.priority}
                                onChange={onPriorityChange}
                                loading={prioritySaving}
                                disabledReason={prioritySaving ? 'Saving priority…' : undefined}
                                size="xsmall"
                                type="tertiary"
                                dropdownPlacement="bottom-end"
                                dropdownMatchSelectWidth={false}
                                menu={{ className: 'w-56' }}
                                options={Object.entries(PRIORITY_MEANING).map(([priority, { label }]) => ({
                                    value: priority as ReportPriorityApi,
                                    label: `${priority} · ${label}`,
                                    labelInMenu: (
                                        <span className="flex items-center gap-2">
                                            <LemonTag
                                                type={PRIORITY_TAG_TYPE[priority as ReportPriorityApi]}
                                                size="small"
                                            >
                                                {priority}
                                            </LemonTag>
                                            <span className="text-default">{label}</span>
                                        </span>
                                    ),
                                }))}
                                renderButtonContent={() => (
                                    <span className="text-default text-xs font-normal">{report.priority}</span>
                                )}
                            />
                        ) : (
                            report.priority
                        )}
                    </StatusRow>
                )}
                {pullRequests.map((pullRequest, index) => {
                    const prUrl = safeHttpUrl(pullRequest.url)
                    const prRef = prUrl ? parsePrUrlParts(prUrl) : null
                    const isOpen = pullRequest.state === 'open' || pullRequest.state === 'draft'

                    return (
                        <div
                            key={pullRequest.id ?? pullRequest.url}
                            className={
                                index === 0
                                    ? 'contents'
                                    : 'contents [&>div:first-child]:border-t [&>div:first-child]:border-primary [&>div:first-child]:pt-3'
                            }
                        >
                            <StatusRow label="Pull request">
                                {prRef && prUrl ? (
                                    <Link to={prUrl} target="_blank">
                                        {prRef.repoSlug}#{prRef.number}
                                    </Link>
                                ) : (
                                    <span className="text-tertiary">Unavailable</span>
                                )}
                            </StatusRow>
                            <StatusRow label="Status">
                                {PULL_REQUEST_STATES[pullRequest.state] ?? PULL_REQUEST_STATES.unknown}
                            </StatusRow>
                            {isOpen && pullRequest.review_decision && (
                                <StatusRow label="Review">{REVIEW_DECISIONS[pullRequest.review_decision]}</StatusRow>
                            )}
                            {pullRequest.state === 'merged' && pullRequest.merged_at && (
                                <StatusRow label="Merged">
                                    <TZLabel time={pullRequest.merged_at} timestampStyle="absolute" />
                                </StatusRow>
                            )}
                        </div>
                    )
                })}
                {trackerUrl && (
                    <StatusRow label="Tracker issue">
                        <Link to={trackerUrl} target="_blank">
                            {report.tracker_issue_reference || 'Open issue'}
                        </Link>
                    </StatusRow>
                )}
            </dl>
        </DetailSection>
    )
}
