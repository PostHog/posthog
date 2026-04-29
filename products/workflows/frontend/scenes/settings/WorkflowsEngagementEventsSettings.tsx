import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

export function WorkflowsEngagementEventsSettings(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const enabled = !!currentTeam?.workflows_config?.capture_engagement_events

    return (
        <LemonSwitch
            id="workflows-capture-engagement-events"
            onChange={(checked) => {
                updateCurrentTeam({
                    workflows_config: {
                        ...currentTeam?.workflows_config,
                        capture_engagement_events: checked,
                    },
                })
            }}
            checked={enabled}
            disabled={userLoading}
            label="Capture email engagement events"
            bordered
        />
    )
}
