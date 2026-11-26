import { useActions } from 'kea'

import { Button } from '@posthog/quill'

import { quillButtonVariant } from 'lib/lemon-ui/LemonButton/quillButtonVariant'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { recommendationsConnectGoogleAdsUrl } from './RecommendationsConnectGoogleAdsButton'
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
            render={<LinkPrimitive to={recommendationsConnectGoogleAdsUrl()} />}
            data-attr="marketing-recommendations-connect-google-ads"
            onClick={() => reportRecommendationsActionClicked('connect_google_ads', location)}
        >
            Connect Google Ads
        </Button>
    )
}
