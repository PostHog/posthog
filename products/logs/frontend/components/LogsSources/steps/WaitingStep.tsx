import { useValues } from 'kea'

import { LemonTag, Spinner } from '@posthog/lemon-ui'

import { logsSourcesLogic } from '../logsSourcesLogic'
import { logsSourceStatusTag } from '../logsSourceStatus'

export function WaitingStep(): JSX.Element {
    const { wizardHealth, wizardSourceIsReceiving } = useValues(logsSourcesLogic)
    const { label, type } = logsSourceStatusTag(wizardHealth?.status, false)
    return (
        <div className="space-y-3">
            <div className="flex items-center gap-2">
                <LemonTag type={type}>{label}</LemonTag>
                {!wizardSourceIsReceiving && <Spinner />}
            </div>
            {wizardSourceIsReceiving ? (
                <p className="m-0 text-secondary">Logs from this source are arriving.</p>
            ) : (
                <p className="m-0 text-secondary">
                    Firehose delivers its first batch about a minute after logs are written to a subscribed log group.
                    PostHog checks every 10 seconds. You can close this window and come back later.
                </p>
            )}
        </div>
    )
}
