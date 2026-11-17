import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import type { WorkflowsConfig } from '~/types'

export function WorkflowsRunLinkTagSettings(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const enabled = currentTeam?.workflows_config?.email_workflow_run_link_tag_enabled ?? true

    return (
        <LemonSwitch
            id="workflows-email-run-link-tag-toggle"
            onChange={(checked) => {
                updateCurrentTeam({
                    workflows_config: {
                        email_workflow_run_link_tag_enabled: checked,
                    } satisfies Partial<WorkflowsConfig> as WorkflowsConfig,
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
