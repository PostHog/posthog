import { useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { HeatmapCaptureSettingsApi } from '../../generated/api.schemas'
import { heatmapCaptureSettingsLogic } from './heatmapCaptureSettingsLogic'

export function shouldShowHeatmapsPricingNotice(settings: HeatmapCaptureSettingsApi | null): boolean {
    return !!settings && !settings.can_capture_all_urls && !settings.enforcement_enabled
}

export function HeatmapsPricingNotice(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam, currentTeamId } = useValues(teamLogic)

    if (!featureFlags[FEATURE_FLAGS.HEATMAPS_PRICING_NOTICE] || !currentTeam?.heatmaps_opt_in || !currentTeamId) {
        return null
    }

    return <HeatmapsPricingNoticeBanner teamId={currentTeamId} />
}

function HeatmapsPricingNoticeBanner({ teamId }: { teamId: number }): JSX.Element | null {
    const { settings, urlAllowlist, captureUrlLimit } = useValues(heatmapCaptureSettingsLogic({ teamId }))

    if (!shouldShowHeatmapsPricingNotice(settings)) {
        return null
    }

    return (
        <LemonBanner
            type="warning"
            dismissKey="heatmaps-pricing-notice"
            action={{
                children: 'Upgrade',
                to: urls.organizationBilling(),
                'data-attr': 'heatmaps-pricing-notice-upgrade',
            }}
        >
            Heatmaps is out of beta, and its pricing changes on November 15. The free plan will collect heatmap data
            from up to {captureUrlLimit} pages, and toolbar heatmaps will need a pay-as-you-go plan.{' '}
            {urlAllowlist.length === 0
                ? 'Your capture list is empty, so heatmaps will stop collecting data. '
                : 'Only the URLs in your capture list will keep collecting data. '}
            <Link
                to={urls.settings('environment-heatmaps', 'heatmaps-capture')}
                data-attr="heatmaps-pricing-notice-review-urls"
            >
                Review capture URLs
            </Link>{' '}
            to choose which pages to keep.{' '}
            <Link
                to="https://posthog.com/docs/toolbar/heatmaps#choosing-which-pages-to-capture"
                target="_blank"
                data-attr="heatmaps-pricing-notice-docs"
            >
                Learn more
            </Link>
        </LemonBanner>
    )
}
