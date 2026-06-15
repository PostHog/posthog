import { useActions, useValues } from 'kea'

import { IconMagicWand } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { isSourceMapsRecommendation, recommendationsTabLogic } from '../recommendations/recommendationsTabLogic'
import { SourceMapsFixModal } from '../recommendations/SourceMapsFixModal'
import { SOURCE_MAPS_DOCS_URL, sourceMapsFixWizardLogic } from '../recommendations/sourceMapsFixWizardLogic'

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
    const lookbackHours = sourceMaps.meta.lookback_hours

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
