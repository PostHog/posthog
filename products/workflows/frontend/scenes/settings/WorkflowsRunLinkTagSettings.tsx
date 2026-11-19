import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonSwitch } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { announceLinkTaggingSaved } from './linkTaggingAcrossTabs'

export function WorkflowsRunLinkTagSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const enabled = currentTeam?.workflows_config?.email_workflow_run_link_tag_enabled ?? true

    // teamLogic replaces the team only after the save commits, so a change of a loaded value means a saved change.
    const loadedEnabled = currentTeam ? enabled : undefined
    const previousEnabled = useRef(loadedEnabled)
    useEffect(() => {
        if (previousEnabled.current !== undefined && previousEnabled.current !== loadedEnabled) {
            announceLinkTaggingSaved()
        }
        previousEnabled.current = loadedEnabled
    }, [loadedEnabled])

    return (
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
    )
}
