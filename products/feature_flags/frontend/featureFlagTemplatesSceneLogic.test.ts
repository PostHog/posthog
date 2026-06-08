import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { featureFlagTemplatesSceneLogic } from './featureFlagTemplatesSceneLogic'

describe('featureFlagTemplatesSceneLogic', () => {
    let logic: ReturnType<typeof featureFlagTemplatesSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('selectedTemplate reducer', () => {
        it.each([
            { name: 'sets template to simple', template: 'simple' as const },
            { name: 'sets template to targeted', template: 'targeted' as const },
            { name: 'sets template to multivariate', template: 'multivariate' as const },
            { name: 'sets template to blank', template: 'blank' as const },
            { name: 'resets template to null', template: null },
        ])('$name', async ({ template }) => {
            logic = featureFlagTemplatesSceneLogic()
            logic.mount()

            logic.actions.setSelectedTemplate(template)

            await expectLogic(logic).toMatchValues({
                selectedTemplate: template,
            })
        })
    })

    describe('intentsEnabled selector', () => {
        it.each([
            { name: 'true when feature flag is on', flagValue: true, expected: true },
            { name: 'false when feature flag is off', flagValue: false, expected: false },
            { name: 'false when feature flag is absent', flagValue: undefined, expected: false },
        ])('$name', async ({ flagValue, expected }) => {
            const flags: Record<string, boolean> = {}
            if (flagValue !== undefined) {
                flags[FEATURE_FLAGS.FEATURE_FLAG_CREATION_INTENTS] = flagValue
            }
            enabledFeaturesLogic.actions.setFeatureFlags([], flags)
            logic = featureFlagTemplatesSceneLogic()
            logic.mount()

            await expectLogic(logic).toMatchValues({
                intentsEnabled: expected,
            })
        })
    })
})
