import { afterMount, connect, kea, path, selectors } from 'kea'
import { combineUrl, router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import type { featureFlagTemplatesSceneLogicType } from './featureFlagTemplatesSceneLogicType'

export const featureFlagTemplatesSceneLogic = kea<featureFlagTemplatesSceneLogicType>([
    path(['products', 'feature_flags', 'frontend', 'featureFlagTemplatesSceneLogic']),
    connect({
        values: [enabledFeaturesLogic, ['featureFlags']],
    }),
    selectors({
        featureFlagsV2Enabled: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.FEATURE_FLAGS_V2],
        ],
    }),
    afterMount(({ values }) => {
        // Redirect to new flag page if V2 is not enabled
        if (!values.featureFlagsV2Enabled) {
            const { searchParams } = router.values
            router.actions.replace(combineUrl(urls.featureFlag('new'), searchParams).url)
        }
    }),
])
