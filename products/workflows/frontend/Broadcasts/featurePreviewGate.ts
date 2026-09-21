import { FEATURE_FLAGS } from 'lib/constants'
import { Scene } from 'scenes/sceneTypes'

import { FeaturePreviewGateConfig } from '~/types'

export const broadcastsFeaturePreviewGate: FeaturePreviewGateConfig = {
    flag: FEATURE_FLAGS.BROADCASTS,
    title: 'Broadcasts is in beta',
    description:
        'Send a one-time or scheduled email to a group of people, and see who received it. Turn it on to try it, and tell us what is missing.',
    docsURL: 'https://posthog.com/docs/workflows',
    // Without this the gate names itself from the router's active scene, which can resolve to
    // Error404 and label the page "Not found".
    sceneId: Scene.Broadcasts,
}
