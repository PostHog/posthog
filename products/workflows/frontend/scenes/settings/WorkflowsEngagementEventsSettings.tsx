import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { engagementEventsLogic } from '../../engagementEventsLogic'

export function WorkflowsEngagementEventsSettings(): JSX.Element {
    const { engagementEventsCaptured, currentTeamLoading } = useValues(engagementEventsLogic)
    const { setEngagementEventsCapture } = useActions(engagementEventsLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <LemonSwitch
            id="workflows-capture-engagement-events"
            onChange={setEngagementEventsCapture}
            checked={engagementEventsCaptured}
            loading={currentTeamLoading}
            disabledReason={restrictedReason}
            label="Capture email engagement events"
            bordered
        />
    )
}
