import type { ExtensionContextValue } from '@stripe/ui-extension-sdk/context'
import { ContextView, Link } from '@stripe/ui-extension-sdk/ui'

import PostHogConnect from '../components/PostHogConnect'
import { BRAND_COLOR, BrandIcon, getConstants } from '../constants'

const APP_ID = 'com.posthog.stripe'

const Home = ({ environment }: ExtensionContextValue): JSX.Element => {
    return (
        <ContextView
            title="PostHog"
            brandColor={BRAND_COLOR}
            brandIcon={BrandIcon}
            footerContent={
                <Link href={{ name: 'fullPage', params: { appId: APP_ID } }} type="primary">
                    Open full dashboard
                </Link>
            }
        >
            <PostHogConnect constants={getConstants(environment)} mode={environment.mode} />
        </ContextView>
    )
}

export default Home
