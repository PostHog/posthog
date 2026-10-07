import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { firstRunMakeItYoursLogic } from './firstRunMakeItYoursLogic'

export function CaptureEngagementEventsSwitch({ templateId }: { templateId: string }): JSX.Element {
    const logic = firstRunMakeItYoursLogic({ templateId })
    const { captureEngagementEvents, captureEngagementEventsDisabledReason } = useValues(logic)
    const { setCaptureEngagementEvents } = useActions(logic)

    return (
        <div className="flex flex-col gap-1">
            <LemonSwitch
                checked={captureEngagementEvents}
                onChange={setCaptureEngagementEvents}
                disabledReason={captureEngagementEventsDisabledReason}
                label="Capture engagement events"
                bordered
                fullWidth
                data-attr="first-run-engagement-events-switch"
            />
            <span className="text-xs text-secondary">
                Records each email sent and delivered as a PostHog event, so you can use them in insights and funnels.
                These events count toward your event usage.
            </span>
        </div>
    )
}
