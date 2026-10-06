import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlow } from '../Workflows/hogflows/types'
import { workflowLogic } from '../Workflows/workflowLogic'
import { firstRunWorkflowBannerLogic } from './firstRunWorkflowBannerLogic'
import { rememberFirstRunWorkflow } from './firstRunWorkflowStorage'

const FIRST_RUN_WORKFLOW_ID = 'wf-first-run'
const OTHER_WORKFLOW_ID = 'wf-other'

function workflow(id: string, status: HogFlow['status']): HogFlow {
    return {
        id,
        name: 'Welcome email sequence',
        description: 'Welcome new signups with an intro email.',
        status,
        version: 1,
        trigger: { type: 'event', filters: { events: [{ id: '$pageview', type: 'events' }] } },
        actions: [],
        edges: [],
        exit_condition: 'exit_only_at_end',
        conversion: { filters: [] },
        updated_at: '2026-10-05T00:00:00Z',
    } as unknown as HogFlow
}

describe('firstRunWorkflowBannerLogic', () => {
    let statuses: Record<string, HogFlow['status']>

    function mountFor(id: string): ReturnType<typeof firstRunWorkflowBannerLogic.build> {
        workflowLogic({ id }).mount()
        const logic = firstRunWorkflowBannerLogic({ id })
        logic.mount()
        return logic
    }

    beforeEach(() => {
        window.localStorage.clear()
        statuses = { [FIRST_RUN_WORKFLOW_ID]: 'draft', [OTHER_WORKFLOW_ID]: 'draft' }
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': ({ params }) => [
                    200,
                    workflow(params.id as string, statuses[params.id as string]),
                ],
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': async ({ params, request }) => {
                    const { status } = (await request.json()) as Partial<HogFlow>
                    statuses[params.id as string] = status ?? statuses[params.id as string]
                    return [200, workflow(params.id as string, statuses[params.id as string])]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_FIRST_RUN], {
            [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: true,
        })
        globalSetupLogic.mount()
        rememberFirstRunWorkflow(FIRST_RUN_WORKFLOW_ID)
    })

    it('shows the draft banner on the first-run draft and highlights Enable', async () => {
        router.actions.push(urls.workflow(FIRST_RUN_WORKFLOW_ID, 'workflow'))
        const logic = mountFor(FIRST_RUN_WORKFLOW_ID)

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ banner: 'draft' })
        expect(globalSetupLogic.values.highlight).toEqual({
            selector: '[data-attr="workflow-launch"]',
            pathname: router.values.location.pathname,
        })
    })

    it('turns into the sending banner once the header enables the workflow', async () => {
        const logic = mountFor(FIRST_RUN_WORKFLOW_ID)
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ banner: 'draft' })

        workflowLogic({ id: FIRST_RUN_WORKFLOW_ID }).actions.saveWorkflowPartial({ status: 'active' })

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ banner: 'sending' })
    })

    it('does not highlight Enable on a sending workflow', async () => {
        statuses[FIRST_RUN_WORKFLOW_ID] = 'active'
        const logic = mountFor(FIRST_RUN_WORKFLOW_ID)

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ banner: 'sending' })
        expect(globalSetupLogic.values.highlight).toBeNull()
    })

    it.each([
        ['another workflow', OTHER_WORKFLOW_ID, true],
        ['the first-run workflow with the flag off', FIRST_RUN_WORKFLOW_ID, false],
    ])('shows nothing on %s', async (_, id, flagOn) => {
        if (!flagOn) {
            featureFlagLogic.actions.setFeatureFlags([], {})
        }
        const logic = mountFor(id)

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ banner: null })
        expect(globalSetupLogic.values.highlight).toBeNull()
    })

    it('keeps a dismissed banner dismissed after enabling and when the workflow opens again', async () => {
        const logic = mountFor(FIRST_RUN_WORKFLOW_ID)
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ banner: 'draft' })

        logic.actions.dismiss()
        workflowLogic({ id: FIRST_RUN_WORKFLOW_ID }).actions.saveWorkflowPartial({ status: 'active' })
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ banner: null })

        logic.unmount()
        const reopened = firstRunWorkflowBannerLogic({ id: FIRST_RUN_WORKFLOW_ID })
        reopened.mount()

        await expectLogic(reopened).toFinishAllListeners().toMatchValues({ banner: null })
    })

    it('opens the Metrics tab from the sending banner', async () => {
        statuses[FIRST_RUN_WORKFLOW_ID] = 'active'
        const logic = mountFor(FIRST_RUN_WORKFLOW_ID)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.viewMetrics()

        expect(removeProjectIdIfPresent(router.values.location.pathname)).toEqual(
            urls.workflow(FIRST_RUN_WORKFLOW_ID, 'metrics')
        )
    })
})
