import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { HeatmapCaptureMode, heatmapCaptureSettingsLogic } from './heatmapCaptureSettingsLogic'

export function shouldShowHeatmapCaptureAllowlistNotice(params: {
    heatmapsOptIn: boolean
    captureMode: HeatmapCaptureMode
    enforcementEnabled: boolean
}): boolean {
    return params.heatmapsOptIn && params.captureMode === 'url_allowlist' && !params.enforcementEnabled
}

export function HeatmapCaptureAllowlistNotice(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam, currentTeamId } = useValues(teamLogic)
    const { settings, urlAllowlist, canCaptureAllUrls, captureUrlLimit } = useValues(
        heatmapCaptureSettingsLogic({ teamId: currentTeamId ?? 0 })
    )

    if (!featureFlags[FEATURE_FLAGS.HEATMAPS_CAPTURE_ALLOWLIST_NOTICE] || !settings) {
        return null
    }

    if (
        !shouldShowHeatmapCaptureAllowlistNotice({
            heatmapsOptIn: !!currentTeam?.heatmaps_opt_in,
            captureMode: settings.capture_mode ?? 'url_allowlist',
            enforcementEnabled: settings.enforcement_enabled,
        })
    ) {
        return null
    }

    if (!canCaptureAllUrls) {
        return (
            <LemonBanner
                type="warning"
                dismissKey="heatmaps-capture-allowlist-notice"
                action={{ children: 'Upgrade', to: urls.organizationBilling() }}
            >
                {urlAllowlist.length === 0
                    ? `When capture limits take effect, heatmaps stop collecting from every page. `
                    : `When capture limits take effect, heatmaps only collect from your listed URLs (up to ${captureUrlLimit}). Every other page stops. `}
                <Link to={urls.settings('environment-heatmaps')}>Review capture URLs</Link> to choose which pages to
                keep.
            </LemonBanner>
        )
    }

    return (
        <LemonBanner
            type="warning"
            dismissKey="heatmaps-capture-allowlist-notice"
            action={{
                children: 'Manage capture URLs',
                onClick: () => router.actions.push(urls.settings('environment-heatmaps')),
            }}
        >
            {urlAllowlist.length === 0
                ? 'Heatmap capture will soon use the URL rules in settings. Add at least one URL, or choose Allow all URLs, to keep collecting heatmap data.'
                : 'Heatmap capture will soon be limited to the URLs you list in settings. Review them to keep collecting the heatmap data you need.'}
        </LemonBanner>
    )
}
