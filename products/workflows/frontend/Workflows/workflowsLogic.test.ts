import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlow } from './hogflows/types'
import { workflowsLogic } from './workflowsLogic'

const draftRow = { id: 'wf-1', name: 'Welcome', status: 'draft' } as HogFlow

describe('workflowsLogic', () => {
    let logic: ReturnType<typeof workflowsLogic.build>
    let patchBodies: Record<string, any>[]
    let requestedTeamIds: string[]
    let detailSenders: HogFlow['unverified_email_senders']

    const mountWith = ({
        flagOn = true,
        senders = [{ id: 7, domain: 'example.com' }],
        team = MOCK_DEFAULT_TEAM,
    }: {
        flagOn?: boolean
        senders?: HogFlow['unverified_email_senders']
        team?: typeof MOCK_DEFAULT_TEAM
    } = {}): void => {
        detailSenders = senders
        initKeaTests(true, team, MOCK_DEFAULT_PROJECT)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_EMAIL_DOMAIN_WIZARD]: flagOn })
        logic = workflowsLogic()
        logic.mount()
    }

    beforeEach(() => {
        patchBodies = []
        requestedTeamIds = []
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/': { results: [], count: 0 },
                '/api/projects/:team_id/hog_flows/': { results: [], count: 0 },
                '/api/environments/:team_id/hog_flows/:id/': ({ params }) => {
                    requestedTeamIds.push(String(params.team_id))
                    return [200, { ...draftRow, unverified_email_senders: detailSenders }]
                },
            },
            patch: {
                '/api/environments/:team_id/hog_flows/:id/': async ({ params, request }) => {
                    requestedTeamIds.push(String(params.team_id))
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
        router.actions.push(
            `${path}?created_by=user-uuid&status=${status}&trigger_type=event&type=messaging&tags=${encodeURIComponent('["growth","billing"]')}`
        )

        expect(logic.values.filters).toEqual({
            search: '',
            createdBy: 'user-uuid',
            status,
            type: 'messaging',
            triggerType: 'event',
            tags: ['growth', 'billing'],
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

    it('reads and saves the workflow in the current environment, not its parent project', async () => {
        const childEnvironmentId = MOCK_DEFAULT_PROJECT.id + 1
        mountWith({ team: { ...MOCK_DEFAULT_TEAM, id: childEnvironmentId } })
        logic.actions.toggleWorkflowStatus(draftRow)
        await expectLogic(logic).toDispatchActions(['openEnablePrompt'])

        await expectLogic(logic, () => {
            logic.actions.confirmEnablePrompt()
        }).toDispatchActions(['confirmEnablePromptSuccess'])
        expect(requestedTeamIds).toEqual([String(childEnvironmentId), String(childEnvironmentId)])
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

    it('saves a row tag edit with only the tags, and shows the name the server stored', async () => {
        mountWith()
        const workflow = { id: 'flow-1', name: 'Churn win-back', tags: [] } as unknown as HogFlow
        const bodies: unknown[] = []
        useMocks({
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': async ({ request }) => {
                    bodies.push(await request.json())
                    return [200, { ...workflow, tags: ['growth'] }]
                },
            },
        })

        await expectLogic(logic, () => logic.actions.updateWorkflowTags(workflow, ['Growth']))
            .toFinishAllListeners()
            .toMatchValues({ localWorkflowTags: { 'flow-1': ['growth'] } })

        expect(bodies).toEqual([{ tags: ['Growth'] }])
    })

    it("sends a row's next tag save only after the one before it lands", async () => {
        mountWith()
        const workflow = { id: 'flow-1', name: 'Churn win-back', tags: [] } as unknown as HogFlow
        const bodies: string[][] = []
        let markFirstInFlight = (): void => {}
        let releaseFirst = (): void => {}
        const firstInFlight = new Promise<void>((resolve) => (markFirstInFlight = resolve))
        const firstReleased = new Promise<void>((resolve) => (releaseFirst = resolve))
        let started = 0
        useMocks({
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': async ({ request }) => {
                    const { tags } = (await request.json()) as { tags: string[] }
                    started += 1
                    if (started === 1) {
                        markFirstInFlight()
                        await firstReleased
                    }
                    bodies.push(tags)
                    return [200, { ...workflow, tags }]
                },
            },
        })

        logic.actions.updateWorkflowTags(workflow, ['growth'])
        logic.actions.updateWorkflowTags(workflow, ['growth', 'billing'])
        await firstInFlight
        releaseFirst()
        await expectLogic(logic).toFinishAllListeners()

        expect(bodies).toEqual([['growth'], ['growth', 'billing']])
        expect(logic.values.localWorkflowTags).toEqual({ 'flow-1': ['growth', 'billing'] })
    })

    it('parses a url whose only filter is a tag', () => {
        mountWith()
        router.actions.push(`/workflows?tags=${encodeURIComponent('["growth"]')}`)

        expect(logic.values.filters.tags).toEqual(['growth'])
    })

    it('keeps the filters when a link back to the list carries no query params', () => {
        mountWith()
        router.actions.push('/workflows?status=active&type=messaging')
        expect(logic.values.filters.status).toEqual('active')

        router.actions.push('/workflows')

        expect(logic.values.filters.status).toEqual('active')
        expect(logic.values.filters.type).toEqual('messaging')
        expect(router.values.searchParams).toMatchObject({ status: 'active', type: 'messaging' })
    })
})
