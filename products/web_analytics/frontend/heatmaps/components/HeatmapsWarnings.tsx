import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function HeatmapsWarnings(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const heatmapsEnabled = currentTeam?.heatmaps_opt_in

    return !heatmapsEnabled ? (
        <LemonBanner
            type="warning"
            action={{
                type: 'secondary',
                icon: <IconGear />,
                to: urls.settings('environment-heatmaps', 'heatmaps'),
                children: 'Configure',
            }}
            dismissKey="heatmaps-might-be-disabled-warning"
        >
            You aren't collecting heatmaps data. Enable heatmaps in your project.
        </LemonBanner>
    ) : null
}
