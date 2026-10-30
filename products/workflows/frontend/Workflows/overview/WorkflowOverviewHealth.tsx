import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

import type { Dayjs } from 'lib/dayjs'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { RATE_LEVEL_TAG, classifyRate, minimumVolumeToClassify } from '../Reputation/emailRateLevels'
import { workflowLogic } from '../workflowLogic'
import { workflowMetricsSummaryLogic } from '../workflowMetricsSummaryLogic'
import { workflowOverviewLogic } from './workflowOverviewLogic'

function HealthItem({
    label,
    value,
    detail,
    tag,
    tooltip,
}: {
    label: string
    value: React.ReactNode
    detail?: React.ReactNode
    tag?: { label: string; type: LemonTagType } | null
    tooltip?: string
}): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col gap-1 px-4 py-3">
            <Tooltip title={tooltip}>
                <span className="text-xs font-semibold text-secondary">{label}</span>
            </Tooltip>
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-lg font-semibold">{value}</span>
                {tag ? (
                    <LemonTag type={tag.type} size="small">
                        {tag.label}
                    </LemonTag>
                ) : null}
            </div>
            {detail ? <span className="text-xs text-muted">{detail}</span> : null}
        </div>
    )
}

function rateItem(
    kind: 'bounce' | 'complaint',
    count: number,
    sent: number,
    detail: string
): { value: string; tag: { label: string; type: LemonTagType } | null; detail: string } {
    if (sent === 0) {
        return { value: '-', tag: null, detail: 'No emails sent' }
    }
    const rate = count / sent
    return {
        value: percentage(rate, 2, true),
        tag: sent < minimumVolumeToClassify(kind) ? null : RATE_LEVEL_TAG[classifyRate(rate, kind)],
        detail,
    }
}

// A failed step does not fail the run when the step continues on error, so the run status filter would miss it.
// Absolute bounds, because Invocations resolves a relative range from the current time rather than the start of the day.
function loggedErrorsUrl(id: string, dateFrom: Dayjs, dateTo: Dayjs): string {
    const search = new URLSearchParams({
        inv_problems: '1',
        inv_date_from: dateFrom.toISOString(),
        inv_date_to: dateTo.toISOString(),
    })
    return `${urls.workflow(id, 'invocations')}?${search.toString()}`
}

export function WorkflowOverviewHealth({
    id,
    logicKey,
    appSourceId,
    period = 'in this date range',
}: {
    id: string
    logicKey: string
    appSourceId?: string
    period?: string
}): JSX.Element {
    const logic = workflowOverviewLogic({ id, logicKey })
    const {
        healthTotals,
        healthTotalsLoading,
        failedRuns,
        stepTotalsLoading,
        stepTotalsFailed,
        healthTotalsFailed,
        retrying,
        getDateRangeAbsolute,
    } = useValues(logic)
    const range = getDateRangeAbsolute()
    const { retry } = useActions(logic)
    const { messagingChannels } = useValues(workflowMetricsSummaryLogic({ logicKey, id, overview: true, appSourceId }))
    const { emailSendingPaused } = useValues(workflowLogic)

    const loading = (healthTotalsLoading && !healthTotals) || (stepTotalsLoading && failedRuns === null)
    const totals = healthTotals ?? {}
    const started = totals.triggered ?? 0
    const emailSent = totals.email_sent ?? 0
    const pushSent = totals.push_sent ?? 0
    // Reputation thresholds apply to permanent bounces only, as on the Reputation page.
    const hardBounces = totals.email_bounced_hard ?? 0
    const bounce = rateItem(
        'bounce',
        hardBounces,
        emailSent,
        `${humanFriendlyNumber(hardBounces)} hard, ${humanFriendlyNumber(totals.email_bounced ?? 0)} bounced in total`
    )
    // Spam complaints are stored under the email_blocked metric name.
    const complaintCount = totals.email_blocked ?? 0
    const complaint = rateItem(
        'complaint',
        complaintCount,
        emailSent,
        `${humanFriendlyNumber(complaintCount)} marked as spam`
    )
    const failed = stepTotalsFailed || healthTotalsFailed

    return (
        <div className="@container rounded border bg-surface-primary" data-attr="workflow-overview-health">
            <div className="flex items-center justify-between gap-2 border-b px-4 py-2">
                <h3 className="mb-0 text-base font-semibold">Health</h3>
                {emailSendingPaused ? (
                    <LemonTag type="danger" data-attr="workflow-overview-health-paused">
                        Email sending paused
                    </LemonTag>
                ) : null}
            </div>
            {failed ? (
                <div className="flex flex-wrap items-center gap-2 p-4 text-sm text-muted">
                    <span>Couldn't load this workflow's health.</span>
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={retry}
                        loading={retrying}
                        data-attr="workflow-overview-health-retry"
                    >
                        Try again
                    </LemonButton>
                </div>
            ) : loading ? (
                <div className="p-4">
                    <LemonSkeleton className="h-12" />
                </div>
            ) : (
                <div className="grid grid-cols-1 divide-y @3xl:auto-cols-fr @3xl:grid-flow-col @3xl:divide-x @3xl:divide-y-0">
                    <HealthItem
                        label="Failed steps"
                        value={humanFriendlyNumber(failedRuns ?? 0)}
                        tag={(failedRuns ?? 0) > 0 ? { label: 'Check logs', type: 'warning' } : RATE_LEVEL_TAG.healthy}
                        tooltip={`Steps that errored ${period}. A failed step either stops the run or continues, depending on the step's error setting.`}
                        detail={
                            (failedRuns ?? 0) > 0 ? (
                                <Link
                                    to={loggedErrorsUrl(id, range.dateFrom, range.dateTo)}
                                    data-attr="workflow-overview-health-failures"
                                >
                                    {`${started > 0 ? `${percentage((failedRuns ?? 0) / started, 1)} of started. ` : ''}View runs with errors`}
                                </Link>
                            ) : (
                                'No errors'
                            )
                        }
                    />
                    {messagingChannels.hasEmail ? (
                        <>
                            <HealthItem
                                label="Hard bounce rate"
                                tooltip="Permanent bounces as a share of emails sent. A high hard bounce rate can pause email from this workflow automatically."
                                {...bounce}
                            />
                            <HealthItem
                                label="Spam complaint rate"
                                tooltip="Spam complaints as a share of emails sent. A high complaint rate can pause email from this workflow automatically."
                                {...complaint}
                            />
                        </>
                    ) : null}
                    {messagingChannels.hasPush ? (
                        <HealthItem
                            label="Push failures"
                            value={humanFriendlyNumber(totals.push_failed ?? 0)}
                            detail={
                                pushSent > 0
                                    ? `${percentage((totals.push_failed ?? 0) / pushSent, 1)} of sent`
                                    : 'No push notifications sent'
                            }
                        />
                    ) : null}
                </div>
            )}
        </div>
    )
}
