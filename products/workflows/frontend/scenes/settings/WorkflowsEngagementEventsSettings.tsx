import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

export function WorkflowsEngagementEventsSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const enabled = !!currentTeam?.workflows_config?.capture_workflows_engagement_events

    return (
        <LemonSwitch
            id="workflows-capture-engagement-events"
            onChange={(checked) => {
                updateCurrentTeam({
                    workflows_config: {
                        ...currentTeam?.workflows_config,
                        capture_workflows_engagement_events: checked,
                    },
                })
            }}
            checked={enabled}
            disabled={currentTeamLoading}
            disabledReason={restrictedReason}
            label="Capture email engagement events"
            bordered
        />
    )
}
