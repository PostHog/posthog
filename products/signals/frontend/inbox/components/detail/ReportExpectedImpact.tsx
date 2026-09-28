import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonModal, LemonTextArea, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport, SignalReportArtefact } from '../../types'
import { asReportMetricSeriesQuery, formatReportMetricValue } from '../../utils/reportMetrics'
import { ReportExpectedImpactChart } from './ReportExpectedImpactChart'

interface MeasurementPlan {
    metric_id: string
    title: string
    kind: ReportMetricApi['kind']
    query?: unknown
    value_format?: ReportMetricApi['value_format']
    unit?: string | null
    goal_value?: number | null
    goal_direction?: ReportMetricApi['goal_direction']
    goal_grain?: 'whole_window' | 'per_interval'
    decision_window_days?: number | null
    minimum_data_points?: number | null
    eligibility_query?: unknown
    activated?: boolean
    retired?: boolean
}

function planFromArtefact(artefact: SignalReportArtefact): MeasurementPlan | null {
    if (artefact.type !== 'impact_measurement_plan') {
        return null
    }
    const content: unknown = artefact.content
    if (
        !content ||
        typeof content !== 'object' ||
        !('metric_id' in content) ||
        typeof content.metric_id !== 'string' ||
        !('title' in content) ||
        typeof content.title !== 'string'
    ) {
        return null
    }
    return content as MeasurementPlan
}

export function ReportExpectedImpact({
    report,
    reportUrl,
    artefacts,
    onApprovalComplete,
}: {
    report: SignalReport
    reportUrl: string
    artefacts?: SignalReportArtefact[] | null
    onApprovalComplete?: () => void
}): JSX.Element {
    const [modalOpen, setModalOpen] = useState(false)
    const [description, setDescription] = useState('')
    const [approvingId, setApprovingId] = useState<string | null>(null)
    const { openReportDiscussion, discussReport } = useActions(inboxTaskKickoffLogic)
    const { aiConsentDisabledReason, isDiscussing, isCreatingPr } = useValues(inboxTaskKickoffLogic)
    const newest = new Map<string, { artefact: SignalReportArtefact; plan: MeasurementPlan }>()
    for (const artefact of artefacts ?? []) {
        const plan = planFromArtefact(artefact)
        if (plan && !newest.has(plan.metric_id)) {
            newest.set(plan.metric_id, { artefact, plan })
        }
    }
    const measurements: {
        metric: ReportMetricApi
        artefact: SignalReportArtefact | null
        eligibilityQuery?: unknown
        goalGrain: 'whole_window' | 'per_interval'
        activated: boolean | undefined
    }[] = [...newest.values()]
        .filter(({ plan }) => !plan.retired)
        .map(({ plan, artefact }) => ({
            metric: {
                metric_id: plan.metric_id,
                title: plan.title,
                kind: plan.kind ?? 'custom',
                query: plan.query,
                value_format: plan.value_format,
                unit: plan.unit,
                goal_value: plan.goal_value,
                goal_direction: plan.goal_direction,
                decision_window_days: plan.decision_window_days,
                minimum_data_points: plan.minimum_data_points,
            },
            artefact,
            eligibilityQuery: plan.eligibility_query,
            goalGrain: plan.goal_grain ?? 'whole_window',
            activated: plan.activated,
        }))
    if (artefacts !== null) {
        for (const metric of report.metrics ?? []) {
            if (metric.goal_value != null && metric.goal_direction && !newest.has(metric.metric_id)) {
                measurements.push({ metric, artefact: null, goalGrain: 'whole_window', activated: false })
            }
        }
    }

    const submit = (): void => {
        const request = description.trim()
        if (!request) {
            return
        }
        openReportDiscussion(report, reportUrl)
        discussReport(report, reportUrl, request, undefined, 'measurement_plan')
        setModalOpen(false)
    }

    const approve = async (artefact: SignalReportArtefact): Promise<void> => {
        setApprovingId(artefact.id)
        try {
            await api.signalReports.activateMeasurement(report.id, artefact.id)
            onApprovalComplete?.()
            lemonToast.success('Measurement approved')
        } catch {
            lemonToast.error('Could not approve this measurement. Please try again.')
        } finally {
            setApprovingId(null)
        }
    }

    return (
        <div className="flex flex-col gap-3 rounded-lg border p-4" data-attr="report-expected-impact">
            {measurements.length ? (
                measurements.map(({ metric, artefact, eligibilityQuery, goalGrain, activated }) => {
                    const query = asReportMetricSeriesQuery(metric)
                    return (
                        <div key={metric.metric_id} className="flex flex-col gap-2">
                            <p className="m-0 font-semibold">
                                {metric.title}:{' '}
                                {metric.goal_value == null
                                    ? 'goal unavailable'
                                    : `${metric.goal_direction === 'at_most' ? 'at most' : 'at least'} ${formatReportMetricValue(metric, metric.goal_value) ?? metric.goal_value}`}
                            </p>
                            <p className="m-0 text-secondary text-sm">
                                {activated ? 'Approved measurement' : 'Proposed measurement'} ·{' '}
                                {goalGrain === 'per_interval'
                                    ? 'Goal per chart interval'
                                    : 'Goal for the full query window'}
                            </p>
                            {query ? (
                                <ReportExpectedImpactChart
                                    reportId={report.id}
                                    metric={metric}
                                    query={query.source}
                                    goalGrain={goalGrain}
                                    version={artefact?.id ?? 'legacy'}
                                />
                            ) : (
                                <p className="text-tertiary m-0">The query is not available to you.</p>
                            )}
                            {(metric.decision_window_days || metric.minimum_data_points) && (
                                <p className="m-0 text-secondary text-sm">
                                    Suggested decision:{' '}
                                    {[
                                        metric.decision_window_days &&
                                            `${metric.decision_window_days} days after release`,
                                        metric.minimum_data_points &&
                                            `${metric.minimum_data_points} qualifying observations`,
                                    ]
                                        .filter(Boolean)
                                        .join(' and ')}
                                    .
                                </p>
                            )}
                            {metric.query != null && (
                                <details className="text-sm">
                                    <summary className="cursor-pointer">View measurement query</summary>
                                    <pre className="max-h-64 overflow-auto rounded bg-surface-secondary p-2 text-xs">
                                        {JSON.stringify(
                                            eligibilityQuery
                                                ? { metric: metric.query, qualifying_opportunities: eligibilityQuery }
                                                : metric.query,
                                            null,
                                            2
                                        )}
                                    </pre>
                                </details>
                            )}
                            {artefact && !activated && metric.query != null && (
                                <div className="flex">
                                    <LemonButton
                                        data-attr="report-expected-impact-approve"
                                        type="secondary"
                                        size="small"
                                        loading={approvingId === artefact.id}
                                        onClick={() => approve(artefact)}
                                    >
                                        Approve measurement
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                    )
                })
            ) : (
                <p className="m-0 text-secondary text-sm">
                    {artefacts === null
                        ? 'Loading proposed measurements…'
                        : 'No measurement proposed yet. Ask AI to find a metric and set a goal.'}
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
