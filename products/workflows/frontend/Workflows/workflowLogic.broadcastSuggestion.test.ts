import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { confirmCreateAsBroadcast } from '../Broadcasts/broadcastLifecycle'
import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'

jest.mock('../Broadcasts/broadcastLifecycle', () => ({
    ...jest.requireActual('../Broadcasts/broadcastLifecycle'),
    confirmCreateAsBroadcast: jest.fn(),
}))

const CREATED_ID = 'created-flow'

const step = (id: string, type: string, config: Record<string, any>): HogFlow['actions'][number] =>
    ({ id, type, name: id, description: '', created_at: 0, updated_at: 0, config }) as HogFlow['actions'][number]

const trigger = (type: string): HogFlow['actions'][number] => step('trigger_node', 'trigger', { type, filters: {} })
const email = step('email_node', 'function_email', { template_id: 'template-email', inputs: {} })
const exit = step('exit_node', 'exit', { reason: 'Default exit' })
const emailEdges: HogFlow['edges'] = [
    { from: 'trigger_node', to: 'email_node', type: 'continue' },
    { from: 'email_node', to: 'exit_node', type: 'continue' },
]

describe('workflowLogic broadcast suggestion on create', () => {
    let logic: ReturnType<typeof workflowLogic.build>
    let createdBodies: Record<string, any>[]
    let convertedIds: string[]
    let submittingDuringMove: boolean[]
    let otherIds: string[]

    beforeEach(() => {
        createdBodies = []
        convertedIds = []
        submittingDuringMove = []
        otherIds = []
        useMocks({
            get: {
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
                '/api/projects/:team_id/hog_flows/broadcast_conversion_candidates/': () => [
                    200,
                    {
                        has_more: false,
                        results: otherIds.map((id) => ({ id, name: id, status: 'draft' })),
                    },
                ],
                '/api/environments/:team_id/hog_flows/:id/schedules': { results: [] },
            },
            post: {
                '/api/projects/:team_id/hog_flows/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, any>
                    createdBodies.push(body)
                    return [201, { ...body, id: CREATED_ID, updated_at: '2026-05-01T00:00:00.000Z' }]
                },
                '/api/projects/:team_id/hog_flows/:id/convert_to_broadcast/': ({ params }) => {
                    convertedIds.push(params.id as string)
                    submittingDuringMove.push(logic.values.isWorkflowSubmitting)
                    return [200, { id: params.id, origin_product: 'broadcasts' }]
                },
            },
        })
        initKeaTests()
        logic = workflowLogic({ id: 'new' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.mocked(confirmCreateAsBroadcast).mockReset()
    })

    it.each([
        {
            name: 'a batch email accepted as a broadcast',
            actions: [trigger('batch'), email, exit],
            exitCondition: 'exit_only_at_end' as const,
            choice: 'broadcast' as const,
            asked: true,
            others: ['wf-a'],
            moved: [],
            originProduct: 'broadcasts',
            path: `/broadcasts/${CREATED_ID}`,
        },
        {
            name: 'a batch email accepted as a broadcast with the others moved',
            actions: [trigger('batch'), email, exit],
            exitCondition: 'exit_only_at_end' as const,
            choice: 'broadcast_and_move' as const,
            asked: true,
            others: ['wf-a', 'wf-b'],
            moved: ['wf-a', 'wf-b'],
            originProduct: 'broadcasts',
            path: `/broadcasts/${CREATED_ID}`,
        },
        {
            name: 'a batch email kept as a workflow',
            actions: [trigger('batch'), email, exit],
            exitCondition: 'exit_only_at_end' as const,
            choice: 'workflow' as const,
            asked: true,
            others: ['wf-a'],
            moved: [],
            originProduct: undefined,
            path: `/workflows/${CREATED_ID}/workflow`,
        },
        {
            name: 'an event-triggered email',
            actions: [trigger('event'), email, exit],
            exitCondition: 'exit_only_at_end' as const,
            choice: 'broadcast' as const,
            asked: false,
            others: [],
            moved: [],
            originProduct: undefined,
            path: `/workflows/${CREATED_ID}/workflow`,
        },
        {
            name: 'a batch email that exits on conversion',
            actions: [trigger('batch'), email, exit],
            exitCondition: 'exit_on_conversion' as const,
            choice: 'broadcast' as const,
            asked: false,
            others: [],
            moved: [],
            originProduct: undefined,
            path: `/workflows/${CREATED_ID}/workflow`,
        },
    ])(
        'creates $name with the right owner and opens it',
        async ({ actions, exitCondition, choice, asked, others, moved, originProduct, path }) => {
            otherIds = others
            jest.mocked(confirmCreateAsBroadcast).mockResolvedValue(choice)
            logic.actions.setWorkflowValues({
                name: 'Monthly update',
                actions,
                edges: emailEdges,
                exit_condition: exitCondition,
            })

            await expectLogic(logic, () => {
                logic.actions.submitWorkflow()
            })
                .toDispatchActions(['saveWorkflowSuccess'])
                .toFinishAllListeners()

            expect(
                jest.mocked(confirmCreateAsBroadcast).mock.calls.map(([offered]) => offered?.map((o) => o.id))
            ).toEqual(asked ? [others] : [])
            expect(convertedIds.sort()).toEqual(moved)
            // Save stays disabled while the other workflows move, so a second click cannot create a duplicate.
            expect(submittingDuringMove).toEqual(moved.map(() => true))
            expect(createdBodies).toHaveLength(1)
            expect(createdBodies[0].origin_product).toBe(originProduct)
            expect(router.values.location.pathname).toMatch(new RegExp(`${path}$`))
        }
    )

    it('creates nothing when the user closes the dialog', async () => {
        jest.mocked(confirmCreateAsBroadcast).mockResolvedValue(null)
        logic.actions.setWorkflowValues({
            name: 'Monthly update',
            actions: [trigger('batch'), email, exit],
            edges: emailEdges,
        })

        await expectLogic(logic, () => {
            logic.actions.submitWorkflow()
        }).toDispatchActions(['submitWorkflowSuccess'])

        expect(createdBodies).toHaveLength(0)
    })
})
