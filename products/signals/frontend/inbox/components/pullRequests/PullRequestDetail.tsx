import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { PRDetailTab, pullRequestsLogic } from '../../logics/pullRequestsLogic'
import { SignalReportStatus } from '../../types'
import { SignalReportStatusBadge } from '../badges/SignalReportStatusBadge'
import { ReportDetail } from '../detail/ReportDetail'
import { MonitorPullRequest } from './MonitorPullRequest'
import { PullRequestOverview } from './PullRequestOverview'

export function PullRequestDetail(): JSX.Element {
    const {
        selectedUrl,
        selectedPR,
        detailTab,
        overview,
        overviewLoading,
        overviewError,
        report,
        reportLoading,
        reportError,
    } = useValues(pullRequestsLogic)
    const { selectPR, setDetailTab, loadOverview, loadReport } = useActions(pullRequestsLogic)
    let body: ReactNode = null
    if (detailTab === 'overview') {
        if (overview?.pull_request.url === selectedUrl) {
            body = <PullRequestOverview overview={overview} />
        } else if (overviewLoading) {
            body = (
                <div className="p-5 space-y-4">
                    <LemonSkeleton className="h-24" />
                    <LemonSkeleton className="h-40" />
                </div>
            )
        }
    } else if (reportError) {
        body = (
            <div className="p-5">
                <LemonBanner
                    type="error"
                    action={{ children: 'Retry', onClick: () => loadReport(selectedPR?.report?.id ?? null) }}
                >
                    Could not load this report.
                </LemonBanner>
            </div>
        )
    } else if (report) {
        body = <ReportDetail key={report.id} report={report} embedded />
    } else if (reportLoading || (overviewLoading && !overview)) {
        body = (
            <div className="p-5">
                <LemonSkeleton className="h-60" />
            </div>
        )
    } else if (selectedPR?.report) {
        body = <div className="p-5 text-secondary">Loading report…</div>
    } else {
        body = <MonitorPullRequest />
    }

    return (
        <section
            aria-label="Pull request details"
            className={clsx('min-w-0 min-h-0 overflow-y-auto', selectedUrl ? 'block' : 'hidden @3xl/inbox:block')}
        >
            {!selectedUrl ? (
                <div className="flex flex-col items-center justify-center p-8 text-center min-h-80 h-full">
                    <h2 className="text-base">See what your changes do</h2>
                    <p className="text-secondary max-w-md">
                        Select a pull request to review its description and CI checks, or monitor its impact on a key
                        metric.
                    </p>
                </div>
            ) : (
                <>
                    <div className="p-5 pb-0">
                        <LemonButton
                            className="@3xl/inbox:hidden mb-3"
                            icon={<IconArrowLeft />}
                            size="small"
                            onClick={() => selectPR(null)}
                        >
                            Pull requests
                        </LemonButton>
                        {selectedPR ? (
                            <>
                                <div className="text-secondary text-sm mb-2 break-all">
                                    {selectedPR.repository} #{selectedPR.number}
                                </div>
                                <h2 className="text-lg break-words mb-3">{selectedPR.title}</h2>
                                <div className="flex flex-wrap gap-2 mb-3">
                                    <LemonTag
                                        type={
                                            selectedPR.state === 'merged'
                                                ? 'completion'
                                                : selectedPR.state === 'closed'
                                                  ? 'danger'
                                                  : 'default'
                                        }
                                    >
                                        {selectedPR.draft && selectedPR.state === 'open'
                                            ? 'Draft'
                                            : selectedPR.state === 'merged'
                                              ? 'Merged'
                                              : selectedPR.state === 'closed'
                                                ? 'Closed'
                                                : 'Open'}
                                    </LemonTag>
                                    {selectedPR.report ? (
                                        <SignalReportStatusBadge
                                            status={report?.status ?? (selectedPR.report.status as SignalReportStatus)}
                                        />
                                    ) : (
                                        <LemonTag>Unmonitored</LemonTag>
                                    )}
                                    {!selectedPR.report && detailTab === 'overview' && (
                                        <LemonButton
                                            type="primary"
                                            size="small"
                                            className="ml-auto"
                                            onClick={() => setDetailTab('report')}
                                            disabledReason={
                                                selectedPR.state === 'closed'
                                                    ? 'This PR was closed without merging.'
                                                    : undefined
                                            }
                                        >
                                            Monitor PR
                                        </LemonButton>
                                    )}
                                </div>
                            </>
                        ) : overviewLoading ? (
                            <LemonSkeleton className="h-16 mb-4" />
                        ) : (
                            <h2 className="text-lg mb-3">Pull request</h2>
                        )}
                        <LemonTabs<PRDetailTab>
                            activeKey={detailTab}
                            onChange={setDetailTab}
                            tabs={[
                                { key: 'overview', label: 'Overview' },
                                { key: 'report', label: 'Report' },
                            ]}
                        />
                    </div>
                    {overviewError && (
                        <div className="px-5 pb-4">
                            <LemonBanner
                                type="error"
                                action={{ children: 'Retry', onClick: () => loadOverview(selectedUrl) }}
                            >
                                Could not refresh this PR.
                            </LemonBanner>
                        </div>
                    )}
                    {detailTab === 'report' &&
                        selectedPR?.state === 'open' &&
                        (report?.status ?? selectedPR.report?.status) === SignalReportStatus.READY && (
                            <div className="px-5 pb-4">
                                <LemonBanner type="info">
                                    Research is ready. Monitoring will start after this PR is merged.
                                </LemonBanner>
                            </div>
                        )}
                    {body}
                </>
            )}
        </section>
    )
}
