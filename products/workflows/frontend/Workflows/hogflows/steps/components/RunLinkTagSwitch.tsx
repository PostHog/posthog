import { useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

export interface RunLinkTagSwitchProps {
    checked: boolean
    onChange: (checked: boolean) => void
    label?: string
    bordered?: boolean
}

export function RunLinkTagSwitch({ checked, onChange, label, bordered }: RunLinkTagSwitchProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const projectEnabled = currentTeam?.workflows_config?.email_workflow_run_link_tag_enabled ?? true

    return (
        <LemonSwitch
            checked={projectEnabled && checked}
            onChange={onChange}
            disabledReason={projectEnabled ? null : 'Connecting clicks to sessions is turned off for this project'}
            label={label}
            aria-label={label ? undefined : 'Connect clicks to sessions'}
            bordered={bordered}
            data-attr="workflow-email-run-link-tag-toggle"
        />
    )
}
