import type { ExtensionContextValue } from '@stripe/ui-extension-sdk/context'
import { ContextView } from '@stripe/ui-extension-sdk/ui'

import PostHogConnect from '../components/PostHogConnect'
import { BRAND_COLOR, BrandIcon, getConstants } from '../constants'

const Home = ({ environment }: ExtensionContextValue): JSX.Element => {
    return (
        <ContextView title="PostHog" brandColor={BRAND_COLOR} brandIcon={BrandIcon}>
            <PostHogConnect constants={getConstants(environment)} mode={environment.mode} />
        </ContextView>
    )
}

export default Home
