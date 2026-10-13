import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { screenshotAccessNotice } from '../heatmapScreenshotCookie'
import { heatmapScreenshotSettingsLogic } from './heatmapScreenshotSettingsLogic'

export function HeatmapScreenshotAccessNotice({ url }: { url: string | null }): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const { settings, loadError } = useValues(heatmapScreenshotSettingsLogic({ teamId: currentTeamId ?? 0 }))
    const message = loadError
        ? 'Could not check screenshot access settings. You can still try the screenshot or check project settings.'
        : screenshotAccessNotice(url, settings)

    return message ? (
        <LemonBanner
            type="info"
            action={{
                children: 'Screenshot settings',
                to: urls.settings('environment-heatmaps', 'heatmap-screenshot-cookie'),
            }}
        >
            {message}
        </LemonBanner>
    ) : null
}
