import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow } from './hogflows/types'
import { workflowsLogic } from './workflowsLogic'

const draftRow = { id: 'wf-1', name: 'Welcome', status: 'draft' } as HogFlow

describe('workflowsLogic', () => {
    let logic: ReturnType<typeof workflowsLogic.build>
    let patchBodies: Record<string, any>[]
    let detailSenders: HogFlow['unverified_email_senders']

    const mountWith = ({
        flagOn = true,
        senders = [{ id: 7, domain: 'example.com' }],
    }: { flagOn?: boolean; senders?: HogFlow['unverified_email_senders'] } = {}): void => {
        detailSenders = senders
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD]: flagOn })
        logic = workflowsLogic()
        logic.mount()
    }

    beforeEach(() => {
        patchBodies = []
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/': { results: [], count: 0 },
                '/api/projects/:team_id/hog_flows/': { results: [], count: 0 },
                '/api/environments/:team_id/hog_flows/:id/': () => [
                    200,
                    { ...draftRow, unverified_email_senders: detailSenders },
                ],
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': async ({ request }) => {
                    patchBodies.push((await request.json()) as Record<string, any>)
                    return [200, { ...draftRow, status: 'waiting_for_domain' }]
                },
            },
        })
    })

    afterEach(() => logic.unmount())

    it.each([
        ['/workflows', 'active'],
        ['/workflows/workflows', 'waiting_for_domain'],
    ])('fills the filters from the query params on %s with status %s', (path, status) => {
        mountWith()
        router.actions.push(`${path}?created_by=user-uuid&status=${status}&trigger_type=event&type=messaging`)

        expect(logic.values.filters).toEqual({
            search: '',
            createdBy: 'user-uuid',
            status,
            type: 'messaging',
            triggerType: 'event',
            page: 1,
        })
        expect(logic.values.paramsFromFilters.status).toEqual(status)
    })

    it('asks before the list toggle enables a workflow with an unverified sender, naming the domain', async () => {
        mountWith()

        await expectLogic(logic, () => {
            logic.actions.toggleWorkflowStatus(draftRow)
        })
            .toDispatchActions(['toggleWorkflowStatusSuccess'])
            .toMatchValues({ enablePrompt: { workflowId: 'wf-1', domains: ['example.com'] } })
        expect(patchBodies).toEqual([])
    })

    it('saves the usual active status once the person confirms', async () => {
        mountWith()
        logic.actions.toggleWorkflowStatus(draftRow)
        await expectLogic(logic).toDispatchActions(['openEnablePrompt'])

        await expectLogic(logic, () => {
            logic.actions.confirmEnablePrompt()
        })
            .toDispatchActions(['loadWorkflows', 'confirmEnablePromptSuccess'])
            .toMatchValues({ enablePrompt: null })
        expect(patchBodies).toEqual([{ status: 'active' }])
    })

    it('leaves the workflow off when the person cancels', async () => {
        mountWith()
        logic.actions.toggleWorkflowStatus(draftRow)
        await expectLogic(logic).toDispatchActions(['openEnablePrompt'])

        await expectLogic(logic, () => {
            logic.actions.cancelEnablePrompt()
        }).toMatchValues({ enablePrompt: null })
        expect(patchBodies).toEqual([])
    })

    it.each([
        ['the flag is off', { flagOn: false }],
        ['every sender is verified', { senders: [] }],
    ])('enables from the list without asking when %s', async (_name, setup) => {
        mountWith(setup)

        await expectLogic(logic, () => {
            logic.actions.toggleWorkflowStatus(draftRow)
        })
            .toDispatchActions(['toggleWorkflowStatusSuccess'])
            .toMatchValues({ enablePrompt: null })
        expect(patchBodies).toEqual([{ status: 'active' }])
    })
})
