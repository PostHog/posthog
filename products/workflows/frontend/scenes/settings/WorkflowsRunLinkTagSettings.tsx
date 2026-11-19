import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

export function WorkflowsRunLinkTagSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const enabled = currentTeam?.workflows_config?.email_workflow_run_link_tag_enabled ?? true

    return (
        <div className="flex flex-col gap-1">
            <LemonSwitch
                id="workflows-email-run-link-tag-toggle"
                onChange={(checked) => {
                    updateCurrentTeam({
                        workflows_config: {
                            email_workflow_run_link_tag_enabled: checked,
                        },
                    })
                }}
                checked={enabled}
                disabled={currentTeamLoading}
                disabledReason={restrictedReason}
                label="Connect tracked email clicks to sessions"
                bordered
                data-attr="workflows-email-run-link-tag-toggle"
            />
            {/* A disabled switch can't take keyboard focus, so its tooltip alone hides the reason from keyboard users */}
            {restrictedReason ? <p className="text-secondary text-sm m-0">{restrictedReason}</p> : null}
        </div>
    )
}
