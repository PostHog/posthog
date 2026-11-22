import { useValues } from 'kea'

import { humanFriendlyLargeNumber, percentage } from 'lib/utils/numbers'

import { MetricLabel } from './MetricLabel'
import { workflowsReputationLogic } from './workflowsReputationLogic'

export function EmailInfrastructureCard(): JSX.Element | null {
    const { infrastructureHealth: health } = useValues(workflowsReputationLogic)
    if (!health) {
        return null
    }
    return (
        <div className="border rounded p-4 bg-surface-primary" data-attr="workflows-reputation-infrastructure">
            <h3 className="mb-0">PostHog email infrastructure</h3>
            <p className="text-secondary mt-2 mb-0">
                Every project in this PostHog region sends email through the same infrastructure. These numbers cover
                all of that email from the last 30 days.
            </p>
            <div className="flex flex-wrap gap-8 mt-3">
                <div>
                    <MetricLabel
                        label="Delivery rate"
                        tooltip="Emails the recipients' mailbox providers accepted, divided by emails sent. A provider can accept an email and still file it as spam."
                    />
                    <div className="text-lg font-semibold">{percentage(health.delivery_rate, 1, true)}</div>
                </div>
                <div>
                    <MetricLabel
                        label="Bounce rate"
                        tooltip="Hard (permanent) bounces divided by emails sent. Transient bounces like a full mailbox are not counted."
                    />
                    <div className="text-lg font-semibold">{percentage(health.bounce_rate, 2, true)}</div>
                </div>
                <div>
                    <MetricLabel
                        label="Spam complaint rate"
                        tooltip="Spam complaints divided by emails delivered to mailbox providers that report complaints."
                    />
                    <div className="text-lg font-semibold">{percentage(health.complaint_rate, 2, true)}</div>
                </div>
                <div>
                    <MetricLabel
                        label="Emails sent (last 30 days)"
                        tooltip="Rounded down, so the real number is higher."
                    />
                    <div className="text-lg font-semibold">
                        {humanFriendlyLargeNumber(health.emails_sent_at_least)}+
                    </div>
                </div>
            </div>
        </div>
    )
}
