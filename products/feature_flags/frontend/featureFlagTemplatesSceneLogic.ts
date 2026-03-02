import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { combineUrl, router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { TemplateKey } from './featureFlagTemplateConstants'
import type { featureFlagTemplatesSceneLogicType } from './featureFlagTemplatesSceneLogicType'

export type SelectedTemplate = TemplateKey | 'blank'

export const featureFlagTemplatesSceneLogic = kea<featureFlagTemplatesSceneLogicType>([
    path(['products', 'feature_flags', 'frontend', 'featureFlagTemplatesSceneLogic']),
    connect({
        values: [enabledFeaturesLogic, ['featureFlags']],
    }),
    actions({
        setSelectedTemplate: (template: SelectedTemplate | null) => ({ template }),
    }),
    reducers({
        selectedTemplate: [
            null as SelectedTemplate | null,
            {
                setSelectedTemplate: (_, { template }) => template,
            },
        ],
    }),
    selectors({
        featureFlagsV2Enabled: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.FEATURE_FLAGS_V2],
        ],
        intentsEnabled: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.FEATURE_FLAG_CREATION_INTENTS],
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
