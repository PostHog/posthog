import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { workflowsSceneLogic } from './WorkflowsScene'

describe('workflowsSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    describe('deep-link to /workflows/suppression', () => {
        // Guards the "flag-off user hits the suppression URL, activeKey stays 'suppression', but
        // the tab isn't in the tabs list" edge case — LemonTabs would render with no matching tab
        // and an empty content area. The logic should fall back to 'workflows' when the flag is off.
        it('falls back to workflows when WORKFLOWS_SUPPRESSION_LIST flag is off', async () => {
            featureFlagLogic.actions.setFeatureFlags([], {})
            const logic = workflowsSceneLogic()
            logic.mount()

            await expectLogic(logic, () => {
                router.actions.push('/workflows/suppression')
            }).toMatchValues({
                currentTab: 'workflows',
            })
        })

        it('honors the suppression tab when the flag is on', async () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SUPPRESSION_LIST], {
                [FEATURE_FLAGS.WORKFLOWS_SUPPRESSION_LIST]: true,
            })
            const logic = workflowsSceneLogic()
            logic.mount()

            await expectLogic(logic, () => {
                router.actions.push('/workflows/suppression')
            }).toMatchValues({
                currentTab: 'suppression',
            })
        })
    })
})
