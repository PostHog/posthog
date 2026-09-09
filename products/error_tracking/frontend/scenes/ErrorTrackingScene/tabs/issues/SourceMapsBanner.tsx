import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconMagicWand, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'

import { isSourceMapsRecommendation, recommendationsTabLogic } from '../recommendations/recommendationsTabLogic'
import { SourceMapsFixModal } from '../recommendations/SourceMapsFixModal'
import { SOURCE_MAPS_DOCS_URL, sourceMapsFixWizardLogic } from '../recommendations/sourceMapsFixWizardLogic'
import { WizardHog } from '../recommendations/sourceMapsWizardVisuals'

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
    const { dismiss } = useActions(lemonBannerLogic({ dismissKey: DISMISS_KEY }))

    useOnMountEffect(() => {
        posthog.capture('error_tracking_source_maps_banner_shown', {
            unresolved_pct: percent,
            lookback_hours: lookbackHours,
        })
    })

    return (
        <>
            <div className="mb-2">
                <div className="rounded-lg border border-border bg-bg-light pl-3 pr-4 py-3 mt-2">
                    <div className="flex items-center gap-4">
                        {/* The hog is absolutely positioned so it doesn't drive the card height —
                            it overflows the card edges slightly by design. */}
                        <div className="relative hidden sm:block shrink-0 self-stretch w-20">
                            <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 pointer-events-none">
                                <div className="absolute -inset-2 bg-[radial-gradient(circle,rgba(43,111,244,0.18),transparent_70%)]" />
                                <WizardHog className="relative w-20 h-20 -rotate-3" />
                            </div>
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className="font-semibold">{percent}% of your stack traces aren't readable</div>
                            <div className="text-sm text-secondary">
                                Let the wizard set up automatic uploads in your project.
                            </div>
                        </div>
                        <LemonButton type="tertiary" size="small" to={SOURCE_MAPS_DOCS_URL} targetBlank>
                            Read docs
                        </LemonButton>
                        <LemonButton type="secondary" icon={<IconMagicWand />} onClick={() => openModal('issues_list')}>
                            <span className="rainbow-text rainbow-text-animating font-semibold">
                                Fix with AI wizard
                            </span>
                        </LemonButton>
                        <LemonButton size="xsmall" icon={<IconX />} onClick={dismiss} aria-label="Dismiss banner" />
                    </div>
                </div>
            </div>
            <SourceMapsFixModal />
        </>
    )
}
