import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { AlertsBanner } from './AlertsBanner'
import { BannerDeck } from './BannerDeck'
import { ErrorTrackingBannerKey } from './bannerQueue'
import { errorTrackingBannersLogic } from './errorTrackingBannersLogic'
import { RateLimitsBanner } from './RateLimitsBanner'
import { SourceMapsBanner } from './SourceMapsBanner'

/** Shows one setup banner at a time, stacked so the user can see and step through the others. */
export function ErrorTrackingBanners(): JSX.Element | null {
    const { activeBanners, currentBanner, sourceMapsRecommendation, alertsRecommendation, rateLimitsRecommendation } =
        useValues(errorTrackingBannersLogic)
    const { showPreviousBanner, showNextBanner } = useActions(errorTrackingBannersLogic)

    if (!currentBanner) {
        return null
    }

    // Keyed by banner so each one mounts fresh and fires its own "shown" event.
    const renderBanner = (banner: ErrorTrackingBannerKey, navigation?: ReactNode): ReactNode => {
        if (banner === 'source_maps' && sourceMapsRecommendation) {
            return <SourceMapsBanner key={banner} recommendation={sourceMapsRecommendation} navigation={navigation} />
        }
        if (banner === 'alerts' && alertsRecommendation) {
            return <AlertsBanner key={banner} recommendation={alertsRecommendation} navigation={navigation} />
        }
        if (banner === 'rate_limits' && rateLimitsRecommendation) {
            return <RateLimitsBanner key={banner} navigation={navigation} />
        }
        return null
    }

    // The sticky filters bar below uses `first:` to detect whether a banner renders above it.
    return (
        <div className="mt-2 mb-2">
            <BannerDeck
                banners={activeBanners}
                current={currentBanner}
                onPrevious={showPreviousBanner}
                onNext={showNextBanner}
                renderCurrent={(navigation) => renderBanner(currentBanner, navigation)}
            />
        </div>
    )
}
