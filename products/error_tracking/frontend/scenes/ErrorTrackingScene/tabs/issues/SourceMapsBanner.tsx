import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconMagicWand } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'

import { isSourceMapsRecommendation, recommendationsTabLogic } from '../recommendations/recommendationsTabLogic'
import { SourceMapsFixModal } from '../recommendations/SourceMapsFixModal'
import { SOURCE_MAPS_DOCS_URL, sourceMapsFixWizardLogic } from '../recommendations/sourceMapsFixWizardLogic'

// Dismissal is independent of the source maps recommendation's own dismissed_at —
// dismissing here only hides this banner, via the standard localStorage-backed pattern.
const DISMISS_KEY = 'error-tracking-source-maps-banner'

export function SourceMapsBanner(): JSX.Element | null {
    const { recommendations } = useValues(recommendationsTabLogic)
    const { isDismissed } = useValues(lemonBannerLogic({ dismissKey: DISMISS_KEY }))

    const sourceMaps = recommendations.find(isSourceMapsRecommendation)
    // Show only once computed and while there's an actual problem (not completed),
    // regardless of whether the recommendation itself was dismissed.
    if (!sourceMaps || sourceMaps.computed_at === null || sourceMaps.completed || isDismissed) {
        return null
    }

    const percent = Math.round((sourceMaps.meta.unresolved_pct ?? 0) * 100)
    const lookbackHours = sourceMaps.meta.lookback_hours

    return <SourceMapsBannerContent percent={percent} lookbackHours={lookbackHours} />
}

// Inner component so the "shown" event fires exactly when the banner becomes visible —
// the outer guards (including dismissal) gate the mount, so mounting here means it was seen.
function SourceMapsBannerContent({ percent, lookbackHours }: { percent: number; lookbackHours: number }): JSX.Element {
    const { openModal } = useActions(sourceMapsFixWizardLogic)

    useOnMountEffect(() => {
        posthog.capture('error_tracking_source_maps_banner_shown', {
            unresolved_pct: percent,
            lookback_hours: lookbackHours,
        })
    })

    return (
        <>
            <LemonBanner
                type="warning"
                className="mb-2"
                dismissKey={DISMISS_KEY}
                action={{
                    children: 'Fix with wizard',
                    icon: <IconMagicWand />,
                    onClick: () => openModal('issues_list'),
                }}
            >
                <div className="flex items-center justify-between gap-2">
                    <span>
                        We detected that {percent}% of your stack frames in the last {lookbackHours} hours are missing
                        source maps, so their stack traces aren't readable. Run the wizard or follow the docs to upload
                        them.
                    </span>
                    <LemonButton type="secondary" to={SOURCE_MAPS_DOCS_URL} targetBlank>
                        Read docs
                    </LemonButton>
                </div>
            </LemonBanner>
            <SourceMapsFixModal />
        </>
    )
}
