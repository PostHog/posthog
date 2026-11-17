import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

export function WorkflowsRunLinkTagSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const enabled = currentTeam?.workflows_config?.email_workflow_run_link_tag_enabled ?? true

    return (
        <LemonSwitch
            id="workflows-email-run-link-tag"
            onChange={(checked) => {
                updateCurrentTeam({
                    workflows_config: {
                        capture_workflows_engagement_events:
                            currentTeam?.workflows_config?.capture_workflows_engagement_events ?? false,
                        email_workflow_run_link_tag_enabled: checked,
                    },
                })
            }}
            checked={enabled}
            disabled={currentTeamLoading}
            label="Add ph_workflow_run to tracked email links"
            bordered
            data-attr="workflows-email-run-link-tag-toggle"
        />
    )
}
