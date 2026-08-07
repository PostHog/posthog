import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

// The setting only governs $heatmap capture, so it being off doesn't mean the view is empty:
// autocapture clickmaps and the SDK enable_heatmaps override both put data on screen without it.
// Warn only when collection is off and this view genuinely came back with nothing to show.
export function shouldWarnHeatmapsOff(heatmapsOptIn: boolean | undefined, viewHasData: boolean | undefined): boolean {
    return !heatmapsOptIn && !viewHasData
}

export function HeatmapsWarnings({ viewHasData }: { viewHasData?: boolean }): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)

    if (!shouldWarnHeatmapsOff(currentTeam?.heatmaps_opt_in, viewHasData)) {
        return null
    }

    return (
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
            Heatmap collection is turned off for this project. Turn it on to capture clicks, scrolls, and mouse
            movement.
        </LemonBanner>
    )
}
