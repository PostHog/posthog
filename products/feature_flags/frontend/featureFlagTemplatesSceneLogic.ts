import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { combineUrl, router } from 'kea-router'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { FlagIntent } from 'scenes/feature-flags/featureFlagIntentWarningLogic'
import { urls } from 'scenes/urls'

import { TemplateKey } from './featureFlagTemplateConstants'
import type { featureFlagTemplatesSceneLogicType } from './featureFlagTemplatesSceneLogicType'

export type SelectedTemplate = TemplateKey | 'blank'

export function navigateToNewFlag(
    searchParams: Record<string, any>,
    template?: SelectedTemplate,
    intent?: FlagIntent
): void {
    const params: Record<string, any> = { ...searchParams }
    if (template && template !== 'blank') {
        params.template = template
    }
    if (intent) {
        params.intent = intent
    }
    router.actions.push(combineUrl(urls.featureFlag('new'), params).url)
}

export const featureFlagTemplatesSceneLogic = kea<featureFlagTemplatesSceneLogicType>([
    path(['products', 'feature_flags', 'frontend', 'featureFlagTemplatesSceneLogic']),
    connect({
        values: [enabledFeaturesLogic, ['featureFlags']],
    }),
    actions({
        setSelectedTemplate: (template: SelectedTemplate | null) => ({ template }),
        selectTemplate: (template: SelectedTemplate) => ({ template }),
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
    listeners(({ actions, values }) => ({
        selectTemplate: ({ template }) => {
            posthog.capture('feature flag template selected', { template_key: template })

            if (values.intentsEnabled) {
                actions.setSelectedTemplate(template)
            } else {
                navigateToNewFlag(router.values.searchParams, template)
            }
        },
    })),
    afterMount(({ values }) => {
        if (!values.featureFlagsV2Enabled) {
            const { searchParams } = router.values
            router.actions.replace(combineUrl(urls.featureFlag('new'), searchParams).url)
        }
    }),
])
