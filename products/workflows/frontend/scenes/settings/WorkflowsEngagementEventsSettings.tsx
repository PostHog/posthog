import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { engagementEventsLogic } from '../../engagementEventsLogic'

export function WorkflowsEngagementEventsSettings(): JSX.Element {
    const { engagementEventsCaptured, currentTeamLoading } = useValues(engagementEventsLogic)
    const { setEngagementEventsCapture } = useActions(engagementEventsLogic)

    return (
        <LemonSwitch
            id="workflows-capture-engagement-events"
            onChange={setEngagementEventsCapture}
            checked={engagementEventsCaptured}
            disabled={currentTeamLoading}
            label="Capture email engagement events"
            bordered
        />
    )
}
