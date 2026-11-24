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
            label: 'Delivery rate',
            tooltip:
                "Emails the recipients' mailbox providers accepted, divided by emails sent. A provider can accept an email and still file it as spam.",
            value: percentage(health.delivery_rate, 1, true),
        },
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
            tooltip: 'Rounded down, so the real number is higher.',
            value: `${humanFriendlyLargeNumber(health.emails_sent_at_least)}+`,
        },
    ]
    return (
        <div
            className={clsx('border border-dashed rounded p-4 bg-surface-secondary text-sm', className)}
            data-attr="workflows-reputation-infrastructure"
        >
            <div className="font-semibold">PostHog email infrastructure</div>
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
