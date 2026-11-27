import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { marketingSourceConnectUrl } from '../components/marketingSourceConnectUrl'
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
            to={marketingSourceConnectUrl('GoogleAds', 'marketing_analytics_recommendations')}
            data-attr="marketing-recommendations-connect-google-ads"
            sideIcon={null}
            onClick={() => reportRecommendationsActionClicked('connect_google_ads', location)}
        >
            Connect Google Ads
        </LemonButton>
    )
}
