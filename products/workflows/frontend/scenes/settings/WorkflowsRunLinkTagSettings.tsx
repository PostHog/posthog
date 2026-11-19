import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { runLinkTaggingEnabled } from './runLinkTagging'

export function WorkflowsRunLinkTagSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const enabled = runLinkTaggingEnabled(currentTeam)

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
            label="Connect tracked email clicks to sessions"
            bordered
            data-attr="workflows-email-run-link-tag-toggle"
        />
    )
}
