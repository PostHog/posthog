import { useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

export const RUN_LINK_TAG_INFO =
    "Connects each tracked link click in this email to the session it starts on your site, including its session replay when recording is on. It works for links to the main domain you send from, or any of its subdomains. When off, this email's links don't get the extra URL parameter that makes the connection."

export interface RunLinkTagSwitchProps {
    checked: boolean
    onChange: (checked: boolean) => void
    'data-attr': string
    label?: string
    bordered?: boolean
}

export function RunLinkTagSwitch({
    checked,
    onChange,
    'data-attr': dataAttr,
    label,
    bordered,
}: RunLinkTagSwitchProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const projectEnabled = currentTeam?.workflows_config?.email_workflow_run_link_tag_enabled ?? true

    return (
        <LemonSwitch
            checked={projectEnabled && checked}
            onChange={onChange}
            disabledReason={projectEnabled ? null : 'Connecting clicks to sessions is turned off for this project'}
            label={label}
            tooltip={label && projectEnabled ? RUN_LINK_TAG_INFO : null}
            aria-label={label ? undefined : 'Connect clicks to sessions'}
            bordered={bordered}
            data-attr={dataAttr}
        />
    )
}
