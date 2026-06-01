import { useActions, useValues } from 'kea'

import { IconMagicWand } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { isSourceMapsRecommendation, recommendationsTabLogic } from '../recommendations/recommendationsTabLogic'
import { SourceMapsFixModal } from '../recommendations/SourceMapsFixModal'
import { sourceMapsFixWizardLogic } from '../recommendations/sourceMapsFixWizardLogic'

// Dismissal is independent of the source maps recommendation's own dismissed_at —
// dismissing here only hides this banner, via the standard localStorage-backed pattern.
const DISMISS_KEY = 'error-tracking-source-maps-banner'

export function SourceMapsBanner(): JSX.Element | null {
    const { recommendations } = useValues(recommendationsTabLogic)
    const { openModal } = useActions(sourceMapsFixWizardLogic)

    const sourceMaps = recommendations.find(isSourceMapsRecommendation)
    // Show only once computed and while there's an actual problem (not completed),
    // regardless of whether the recommendation itself was dismissed.
    if (!sourceMaps || sourceMaps.computed_at === null || sourceMaps.completed) {
        return null
    }

    const percent = Math.round((sourceMaps.meta.unresolved_pct ?? 0) * 100)

    return (
        <>
            <LemonBanner
                type="warning"
                className="mb-2"
                dismissKey={DISMISS_KEY}
                action={{ children: 'Fix with wizard', icon: <IconMagicWand />, onClick: openModal }}
            >
                We detected that {percent}% of your stack frames in the last {sourceMaps.meta.lookback_hours} hours are
                missing source maps, so their stack traces aren't readable. Run the setup wizard to upload them.
            </LemonBanner>
            <SourceMapsFixModal />
        </>
    )
}
