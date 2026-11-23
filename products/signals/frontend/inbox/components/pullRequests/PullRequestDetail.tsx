import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconPullRequest, IconTarget } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { PRBrowserItemApi, PRBrowserOverviewApi } from '../../../generated/api.schemas'
import { capturePRAction, pullRequestsLogic } from '../../logics/pullRequestsLogic'
import { SignalReportStatus } from '../../types'
import { inboxReportDetailUrl } from '../../utils/inboxReportUrls'
import { SignalReportStatusBadge } from '../badges/SignalReportStatusBadge'
import { DetailSection } from '../detail/DetailSection'
import { MonitorPullRequest } from './MonitorPullRequest'
import { PullRequestOverview } from './PullRequestOverview'
import { pullRequestStateColor, pullRequestStateLabel } from './PullRequestRow'

function monitoredReportDescription(status: SignalReportStatus, prState: string): string {
    switch (status) {
        case SignalReportStatus.CANDIDATE:
        case SignalReportStatus.IN_PROGRESS:
            return 'An agent is inspecting this pull request and choosing a key metric to watch.'
        case SignalReportStatus.READY:
            return prState === 'open'
                ? 'Research is ready. Monitoring will start after this pull request merges.'
                : 'Research is ready for this pull request.'
        case SignalReportStatus.MONITORING:
            return "PostHog is checking this pull request's post-merge impact."
        case SignalReportStatus.PENDING_INPUT:
            return 'This report needs your input before impact can be measured.'
        case SignalReportStatus.RESOLVED:
        case SignalReportStatus.CLOSED:
            return "PostHog finished checking this pull request's post-merge window."
        default:
            return 'Linked to a self-driving report.'
    }
}

function PullRequestDetailHeader({
    selectedPR,
    matchedOverview,
    overviewLoading,
}: {
    selectedPR: PRBrowserItemApi | null
    matchedOverview: PRBrowserOverviewApi | null
    overviewLoading: boolean
}): JSX.Element {
    if (!selectedPR) {
        return overviewLoading ? (
            <LemonSkeleton className="h-12" />
        ) : (
            <h3 className="m-0 text-sm font-semibold">Pull request</h3>
        )
    }

    return (
        <>
            <div className="flex items-start gap-2">
                <span className={clsx('mt-0.5 flex shrink-0 items-center', pullRequestStateColor(selectedPR))}>
                    <IconPullRequest className="size-4" />
                </span>
                <h3 className="m-0 min-w-0 flex-1 break-words text-sm font-semibold leading-snug text-primary">
                    {selectedPR.title}
                </h3>
            </div>
            <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 pl-6 text-xs text-tertiary">
                <span className="font-mono text-secondary">
                    {selectedPR.repository}#{selectedPR.number}
                </span>
                <span>·</span>
                <span>{pullRequestStateLabel(selectedPR)}</span>
                <span>·</span>
                <span>@{selectedPR.author}</span>
                <span>·</span>
                <TZLabel time={selectedPR.created_at} />
            </div>
            {matchedOverview ? (
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 pl-6 pt-0.5 text-xs text-secondary">
                    <span className="break-all font-mono text-[11px] text-tertiary">
                        {matchedOverview.head_branch} → {matchedOverview.base_branch}
                    </span>
                    <span className="text-[11px] text-tertiary">
                        {matchedOverview.changed_files} {matchedOverview.changed_files === 1 ? 'file' : 'files'}
                    </span>
                    <span className="font-mono text-[11px] tabular-nums">
                        <span className="text-success">+{matchedOverview.additions}</span>{' '}
                        <span className="text-danger">−{matchedOverview.deletions}</span>
                    </span>
                </div>
            ) : null}
        </>
    )
}

function ImpactMonitoringContent({ selectedPR }: { selectedPR: PRBrowserItemApi | null }): JSX.Element {
    const { monitoringRequestLoading, monitorError } = useValues(pullRequestsLogic)
    const { monitorPR } = useActions(pullRequestsLogic)

    if (!selectedPR) {
        return <></>
    }

    const reportRef = selectedPR.report
    if (!reportRef) {
        return <MonitorPullRequest />
    }

    const reportStatus = reportRef.status as SignalReportStatus
    if (reportStatus === SignalReportStatus.FAILED) {
        return (
            <div className="space-y-2">
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Retry research',
                        loading: monitoringRequestLoading,
                        onClick: () => monitorPR(),
                    }}
                >
                    Pull request monitoring research failed before a measurement was saved.
                </LemonBanner>
                {monitorError ? <LemonBanner type="error">{monitorError}</LemonBanner> : null}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2.5">
            <p className="m-0 text-xs text-secondary">{monitoredReportDescription(reportStatus, selectedPR.state)}</p>
            <LemonButton
                type="secondary"
                size="small"
                className="self-start"
                to={inboxReportDetailUrl(reportRef.id, urls.inbox('monitoring'))}
                data-attr="inbox-pr-open-report"
                onClick={() => capturePRAction('open_report')}
            >
                Open report
            </LemonButton>
        </div>
    )
}

function PullRequestOverviewSection({
    selectedUrl,
    matchedOverview,
}: {
    selectedUrl: string
    matchedOverview: PRBrowserOverviewApi | null
}): JSX.Element {
    const { overviewLoading, overviewError } = useValues(pullRequestsLogic)
    const { loadPullRequestOverview } = useActions(pullRequestsLogic)

    if (overviewError) {
        return (
            <div className="p-3.5">
                <LemonBanner
                    type="error"
                    action={{ children: 'Retry', onClick: () => loadPullRequestOverview(selectedUrl) }}
                >
                    Could not load pull request details.
                </LemonBanner>
            </div>
        )
    }

    if (matchedOverview) {
        return <PullRequestOverview overview={matchedOverview} />
    }

    if (overviewLoading) {
        return (
            <div className="space-y-3 p-3.5">
                <LemonSkeleton className="h-16" />
                <LemonSkeleton className="h-24" />
            </div>
        )
    }

    return <></>
}

export function PullRequestDetail(): JSX.Element {
    const { selectedUrl, selectedPR, overview, overviewLoading } = useValues(pullRequestsLogic)

    if (!selectedUrl) {
        return <></>
    }

    const reportStatus = selectedPR?.report ? (selectedPR.report.status as SignalReportStatus) : null
    const matchedOverview = overview?.pull_request.url === selectedUrl ? overview : null

    return (
        <section aria-label="Pull request details" className="flex min-w-0 flex-col">
            <div className="flex flex-col gap-1.5 border-b border-primary px-3.5 py-3">
                <PullRequestDetailHeader
                    selectedPR={selectedPR}
                    matchedOverview={matchedOverview}
                    overviewLoading={overviewLoading}
                />
            </div>

            <div className="border-b border-primary px-3.5 py-3">
                <DetailSection
                    icon={<IconTarget />}
                    title="Impact monitoring"
                    rightSlot={reportStatus ? <SignalReportStatusBadge status={reportStatus} /> : undefined}
                >
                    <ImpactMonitoringContent selectedPR={selectedPR} />
                </DetailSection>
            </div>

            <PullRequestOverviewSection selectedUrl={selectedUrl} matchedOverview={matchedOverview} />
        </section>
    )
}
