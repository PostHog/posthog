import { useActions } from 'kea'

import { Button } from '@posthog/quill'

import { quillButtonVariant } from 'lib/lemon-ui/LemonButton/quillButtonVariant'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { marketingSourceConnectUrl } from '../components/marketingSourceConnectUrl'
import { recommendationsLogic } from './recommendationsLogic'

export function QuillRecommendationsConnectGoogleAdsButton({
    type,
    location,
}: {
    type: 'secondary' | 'tertiary'
    location: 'section_empty' | 'section_campaigns'
}): JSX.Element {
    const { reportRecommendationsActionClicked } = useActions(recommendationsLogic)

    return (
        <Button
            variant={quillButtonVariant(type)}
            render={
                <LinkPrimitive to={marketingSourceConnectUrl('GoogleAds', 'marketing_analytics_recommendations')} />
            }
            data-attr="marketing-recommendations-connect-google-ads"
            onClick={() => reportRecommendationsActionClicked('connect_google_ads', location)}
        >
            Connect Google Ads
        </Button>
    )
}
