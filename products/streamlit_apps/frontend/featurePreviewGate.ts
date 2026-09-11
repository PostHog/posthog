import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'
import { FeaturePreviewGateConfig } from '~/types'

export const streamlitAppsFeaturePreviewGate: FeaturePreviewGateConfig = {
    flag: FEATURE_FLAGS.STREAMLIT_APPS,
    title: 'Try Streamlit apps',
    description:
        'Build and share Python apps that run on your PostHog data. This is an early preview, so expect rough edges. Turn it on below to build your first app.',
    sceneId: 'StreamlitApps',
    productIntent: ProductKey.STREAMLIT_APPS,
    offerRequestAccess: true,
}
