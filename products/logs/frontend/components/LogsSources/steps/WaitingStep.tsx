import { useValues } from 'kea'

import { LemonTag, Spinner } from '@posthog/lemon-ui'

import { logsSourcesLogic } from '../logsSourcesLogic'
import { logsSourceStatusLabel, logsSourceStatusTagType } from '../logsSourceStatus'

export function WaitingStep(): JSX.Element {
    const { wizardHealth } = useValues(logsSourcesLogic)
    const status = wizardHealth?.status
    return (
        <div className="space-y-3">
            <div className="flex items-center gap-2">
                <LemonTag type={logsSourceStatusTagType(status)}>{logsSourceStatusLabel(status)}</LemonTag>
                {status !== 'receiving' && <Spinner />}
            </div>
            {status === 'receiving' ? (
                <p className="m-0 text-secondary">
                    Logs from this source are arriving. Open the Logs page to explore them.
                </p>
            ) : (
                <p className="m-0 text-secondary">
                    Firehose delivers its first batch about a minute after logs are written to a subscribed log group.
                    This page checks every 10 seconds. You can close this window and come back later.
                </p>
            )}
        </div>
    )
}
