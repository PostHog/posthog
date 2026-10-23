import { nativeSourceDisplayLabel } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { NativeMarketingSource } from '~/queries/schema/schema-general'

import IconAmazonAds from 'public/services/amazon_ads.png'
import IconAppleAds from 'public/services/apple_search_ads.png'
import IconBingAds from 'public/services/bing-ads.svg'
import IconGoogleAds from 'public/services/google-ads.png'
import IconLinkedinAds from 'public/services/linkedin.png'
import IconMetaAds from 'public/services/meta-ads.png'
import IconOpenAIAds from 'public/services/openai_ads.svg'
import IconPinterestAds from 'public/services/pinterest_ads.png'
import IconRedditAds from 'public/services/reddit.png'
import IconRoktAds from 'public/services/rokt_ads.png'
import IconSnapchatAds from 'public/services/snapchat.png'
import IconTikTokAds from 'public/services/tiktok.png'
import IconTwitterAds from 'public/services/twitter_ads.png'

const LOGOS: Record<NativeMarketingSource, string> = {
    GoogleAds: IconGoogleAds,
    MetaAds: IconMetaAds,
    LinkedinAds: IconLinkedinAds,
    TikTokAds: IconTikTokAds,
    RedditAds: IconRedditAds,
    BingAds: IconBingAds,
    SnapchatAds: IconSnapchatAds,
    PinterestAds: IconPinterestAds,
    AppleSearchAds: IconAppleAds,
    OpenAIAds: IconOpenAIAds,
    AmazonAds: IconAmazonAds,
    RoktAds: IconRoktAds,
    TwitterAds: IconTwitterAds,
}

const SIZE_CLASSES = {
    small: 'size-4',
    medium: 'size-5',
}

export function AdPlatformLogo({
    platform,
    size = 'small',
}: {
    platform: NativeMarketingSource
    size?: keyof typeof SIZE_CLASSES
}): JSX.Element {
    return (
        <img
            src={LOGOS[platform]}
            alt={nativeSourceDisplayLabel(platform)}
            className={`${SIZE_CLASSES[size]} shrink-0 rounded-sm object-contain`}
        />
    )
}
