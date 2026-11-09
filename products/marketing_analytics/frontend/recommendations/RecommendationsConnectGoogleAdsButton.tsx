import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { recommendationsLogic } from './recommendationsLogic'

export function RecommendationsConnectGoogleAdsButton({
    type,
    location,
}: {
    type: 'secondary' | 'tertiary'
    location: 'section_empty' | 'section_campaigns'
}): JSX.Element {
    const { reportRecommendationsActionClicked } = useActions(recommendationsLogic)

    return (
        <LemonButton
            type={type}
            size="small"
            // pinned: entry_point on the source connect events, renaming it splits the attribution
            to={urls.dataWarehouseSourceNew(
                'GoogleAds',
                urls.marketingAnalyticsApp(),
                'Marketing analytics',
                undefined,
                'marketing_analytics_recommendations'
            )}
            data-attr="marketing-recommendations-connect-google-ads"
            sideIcon={null}
            onClick={() => reportRecommendationsActionClicked('connect_google_ads', location)}
        >
            Connect Google Ads
        </LemonButton>
    )
}
