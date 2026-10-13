import { useValues } from 'kea'

import { LemonSkeleton, LemonTag, LemonTagType, Link, Tooltip } from '@posthog/lemon-ui'

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
    sent: number
): { value: string; tag: { label: string; type: LemonTagType } | null; detail: string } {
    const noun = kind === 'bounce' ? 'bounced' : 'marked as spam'
    if (sent === 0) {
        return { value: '-', tag: null, detail: 'No emails sent' }
    }
    const rate = count / sent
    return {
        value: percentage(rate, 2, true),
        tag: sent < minimumVolumeToClassify(kind) ? null : RATE_LEVEL_TAG[classifyRate(rate, kind)],
        detail: `${humanFriendlyNumber(count)} ${noun}`,
    }
}

// A failed step does not fail the run when the step continues on error, so the run status filter would miss it.
function loggedErrorsUrl(id: string, dateFrom?: string | null, dateTo?: string | null): string {
    const search = new URLSearchParams({ inv_problems: '1', inv_date_from: dateFrom ?? '-7d' })
    if (dateTo) {
        search.set('inv_date_to', dateTo)
    }
    return `${urls.workflow(id, 'invocations')}?${search.toString()}`
}

export function WorkflowOverviewHealth({ id, logicKey }: { id: string; logicKey: string }): JSX.Element {
    const { healthTotals, healthTotalsLoading, failedRuns, stepTotalsLoading, params } = useValues(
        workflowOverviewLogic({ id, logicKey })
    )
    const { messagingChannels } = useValues(workflowMetricsSummaryLogic({ logicKey, id }))
    const { emailSendingPaused } = useValues(workflowLogic)

    const loading = (healthTotalsLoading && !healthTotals) || (stepTotalsLoading && failedRuns === null)
    const totals = healthTotals ?? {}
    const started = totals.triggered ?? 0
    const emailSent = totals.email_sent ?? 0
    const pushSent = totals.push_sent ?? 0
    const bounce = rateItem('bounce', totals.email_bounced ?? 0, emailSent)
    // Spam complaints are stored under the email_blocked metric name.
    const complaint = rateItem('complaint', totals.email_blocked ?? 0, emailSent)

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
            {loading ? (
                <div className="p-4">
                    <LemonSkeleton className="h-12" />
                </div>
            ) : (
                <div className="grid grid-cols-1 divide-y @3xl:auto-cols-fr @3xl:grid-flow-col @3xl:divide-x @3xl:divide-y-0">
                    <HealthItem
                        label="Failed steps"
                        value={humanFriendlyNumber(failedRuns ?? 0)}
                        tag={(failedRuns ?? 0) > 0 ? { label: 'Check logs', type: 'warning' } : RATE_LEVEL_TAG.healthy}
                        tooltip="Steps that errored in this date range. A failed step either stops the run or continues, depending on the step's error setting."
                        detail={
                            (failedRuns ?? 0) > 0 ? (
                                <Link
                                    to={loggedErrorsUrl(id, params.dateFrom, params.dateTo)}
                                    data-attr="workflow-overview-health-failures"
                                >
                                    {started > 0 ? `${percentage((failedRuns ?? 0) / started, 1)} of started. ` : ''}
                                    View runs with errors
                                </Link>
                            ) : (
                                'No errors'
                            )
                        }
                    />
                    {messagingChannels.hasEmail ? (
                        <>
                            <HealthItem
                                label="Bounce rate"
                                tooltip="Bounces as a share of emails sent. A high bounce rate can pause email from this workflow automatically."
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
