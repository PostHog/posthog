import { router } from 'kea-router'
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
            enabledFeaturesLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.FEATURE_FLAGS_V2]: true,
            })
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
            const flags: Record<string, boolean> = {
                [FEATURE_FLAGS.FEATURE_FLAGS_V2]: true,
            }
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

    describe('afterMount redirect', () => {
        it('redirects to new flag page when V2 is disabled', async () => {
            enabledFeaturesLogic.actions.setFeatureFlags([], {})
            logic = featureFlagTemplatesSceneLogic()
            logic.mount()

            await expectLogic(router).toMatchValues({
                location: expect.objectContaining({
                    pathname: expect.stringContaining('/feature_flags/new'),
                }),
            })
        })

        it('does not redirect when V2 is enabled', async () => {
            enabledFeaturesLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.FEATURE_FLAGS_V2]: true,
            })
            const currentPath = router.values.location.pathname
            logic = featureFlagTemplatesSceneLogic()
            logic.mount()

            await expectLogic(router).toMatchValues({
                location: expect.objectContaining({
                    pathname: currentPath,
                }),
            })
        })
    })
})
