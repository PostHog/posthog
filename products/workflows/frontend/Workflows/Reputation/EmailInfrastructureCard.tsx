import clsx from 'clsx'
import { useValues } from 'kea'

import { humanFriendlyLargeNumber, percentage } from 'lib/utils/numbers'

import { MetricLabel } from './MetricLabel'
import { workflowsReputationLogic } from './workflowsReputationLogic'

export function EmailInfrastructureCard({ className }: { className?: string }): JSX.Element | null {
    const { infrastructureHealth: health } = useValues(workflowsReputationLogic)
    if (!health) {
        return null
    }
    const metrics = [
        {
            label: 'Bounce rate',
            tooltip:
                'Hard (permanent) bounces divided by emails sent. Transient bounces like a full mailbox are not counted.',
            value: percentage(health.bounce_rate, 2, true),
        },
        {
            label: 'Spam complaint rate',
            tooltip: 'Spam complaints divided by emails delivered to mailbox providers that report complaints.',
            value: percentage(health.complaint_rate, 2, true),
        },
        {
            label: 'Emails sent',
            tooltip: 'Rounded down to a lower bound, so the real number can be higher.',
            value: `${humanFriendlyLargeNumber(health.emails_sent_at_least)}+`,
        },
    ]
    return (
        <div
            className={clsx('border border-dashed rounded p-4 bg-surface-secondary text-sm', className)}
            data-attr="workflows-reputation-infrastructure"
        >
            <h3 className="text-sm font-semibold mb-0">PostHog email infrastructure</h3>
            <p className="text-secondary text-xs mt-1 mb-0">
                All email sent by every project in this region in the last 30 days, not only this project's.
            </p>
            <dl className="mt-3 mb-0 space-y-1">
                {metrics.map((metric) => (
                    <div key={metric.label} className="flex items-baseline justify-between gap-4">
                        <dt>
                            <MetricLabel label={metric.label} tooltip={metric.tooltip} />
                        </dt>
                        <dd className="m-0 font-semibold">{metric.value}</dd>
                    </div>
                ))}
            </dl>
        </div>
    )
}
