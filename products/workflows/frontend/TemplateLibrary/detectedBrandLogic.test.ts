import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowsSceneLogic } from '../WorkflowsScene'
import { detectedBrandLogic } from './detectedBrandLogic'

describe('detectedBrandLogic', () => {
    let detections: number

    beforeEach(() => {
        detections = 0
        useMocks({
            post: {
                '/api/projects/:team_id/messaging_templates/detect_brand/': () => {
                    detections++
                    return [200, { website: null, name: null, primary_color: null, logo_url: null }]
                },
            },
        })
        initKeaTests()
    })

    it.each([
        [true, 1],
        [false, 0],
    ])('asks for the brand as Workflows opens when the starter flag is %s', async (flagOn, expected) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.EMAIL_BRANDED_STARTER]: flagOn })

        workflowsSceneLogic({}).mount()

        await expectLogic(detectedBrandLogic).toFinishAllListeners()
        expect(detections).toBe(expected)
    })

    it('asks for the brand once the starter flag turns on after Workflows opened', async () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.EMAIL_BRANDED_STARTER]: false })
        workflowsSceneLogic({}).mount()

        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.EMAIL_BRANDED_STARTER]: true })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.EMAIL_BRANDED_STARTER]: true })

        await expectLogic(detectedBrandLogic).toFinishAllListeners()
        expect(detections).toBe(1)
    })
})
