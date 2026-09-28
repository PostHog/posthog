import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonModal, LemonTextArea, lemonToast } from '@posthog/lemon-ui'

import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport } from '../../types'
import { asReportMetricSeriesQuery, formatReportMetricValue } from '../../utils/reportMetrics'
import { ReportExpectedImpactChart } from './ReportExpectedImpactChart'

export function ReportExpectedImpact({ report, reportUrl }: { report: SignalReport; reportUrl: string }): JSX.Element {
    const [modalOpen, setModalOpen] = useState(false)
    const [description, setDescription] = useState('')
    const { openReportDiscussion, discussReport } = useActions(inboxTaskKickoffLogic)
    const { aiConsentDisabledReason, isDiscussing, isCreatingPr } = useValues(inboxTaskKickoffLogic)
    const proposedMetrics =
        report.metrics?.filter(
            (metric) =>
                metric.goal_value != null &&
                metric.goal_direction &&
                (metric.decision_window_days || metric.minimum_data_points)
        ) ?? []

    const submit = (): void => {
        const request = description.trim()
        if (!request) {
            return
        }
        const question = `Update only the Expected impact section and proposed measurement on this report. Investigate which data is available, then use the inbox report edit tool to write a clear, testable success goal. Add or update a live report metric with a bounded query, goal_value, goal_direction, and a short decision_window_days or minimum_data_points justified by the expected volume. Count eligible opportunities, not failures, as data points. Keep the other report metrics and sections intact. If the data is not available, say what is missing; do not invent a chart or a threshold. Do not create a follow-up check, start monitoring, change the report status, or open a PR. The user's idea: ${request}`
        openReportDiscussion(report, reportUrl)
        discussReport(report, reportUrl, question)
        setModalOpen(false)
        setDescription('')
    }

    return (
        <div className="flex flex-col gap-3 rounded-lg border p-4" data-attr="report-expected-impact">
            {proposedMetrics.length ? (
                proposedMetrics.map((metric) => {
                    const query = asReportMetricSeriesQuery(metric)
                    return (
                        <div key={metric.metric_id} className="flex flex-col gap-2">
                            <p className="m-0 font-semibold">
                                {metric.title}: {metric.goal_direction === 'at_most' ? 'at most' : 'at least'}{' '}
                                {formatReportMetricValue(metric, metric.goal_value) ?? metric.goal_value}
                            </p>
                            {query ? (
                                <ReportExpectedImpactChart reportId={report.id} metric={metric} query={query.source} />
                            ) : (
                                <p className="text-tertiary m-0">The query is not available to you.</p>
                            )}
                            <p className="m-0 text-secondary text-sm">
                                Suggested decision:{' '}
                                {[
                                    metric.decision_window_days && `${metric.decision_window_days} days after release`,
                                    metric.minimum_data_points &&
                                        `${metric.minimum_data_points} qualifying observations`,
                                ]
                                    .filter(Boolean)
                                    .join(' and ')}
                                .
                            </p>
                            {metric.query != null && (
                                <details className="text-sm">
                                    <summary className="cursor-pointer">View measurement query</summary>
                                    <pre className="max-h-64 overflow-auto rounded bg-surface-secondary p-2 text-xs">
                                        {JSON.stringify(metric.query, null, 2)}
                                    </pre>
                                </details>
                            )}
                        </div>
                    )
                })
            ) : (
                <p className="m-0 text-secondary text-sm">
                    No measurement proposed yet. Ask AI to find a metric and set a goal.
                </p>
            )}
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    data-attr="report-expected-impact-follow-up"
                    type="primary"
                    size="small"
                    onClick={() => lemonToast.info('Coming soon: automatic impact follow-ups are not available yet.')}
                >
                    Keep an eye on this for me
                </LemonButton>
                <LemonButton
                    data-attr="report-expected-impact-suggest-metrics"
                    type="secondary"
                    size="small"
                    onClick={() => setModalOpen(true)}
                >
                    Suggest different metrics
                </LemonButton>
            </div>
            <LemonModal
                isOpen={modalOpen}
                onClose={() => setModalOpen(false)}
                title="Describe what success would look like"
                width={560}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setModalOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            data-attr="report-expected-impact-submit-suggestion"
                            type="primary"
                            onClick={submit}
                            loading={isDiscussing}
                            disabledReason={
                                aiConsentDisabledReason ??
                                (isCreatingPr ? 'An implementation is starting.' : undefined) ??
                                (!description.trim() ? 'Describe the outcome first.' : undefined)
                            }
                        >
                            Ask AI to update report
                        </LemonButton>
                    </>
                }
            >
                <LemonTextArea
                    value={description}
                    onChange={setDescription}
                    placeholder="For example, fewer users should see the not-found page within a week."
                    rows={4}
                    maxLength={2000}
                    data-attr="report-expected-impact-description"
                />
            </LemonModal>
        </div>
    )
}
