import { act, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { createElement } from 'react'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow } from './hogflows/types'
import { canMoveToBroadcasts, workflowBroadcastMoveLogic } from './workflowBroadcastMoveLogic'

const step = (id: string, type: string, config: Record<string, any>): HogFlow['actions'][number] =>
    ({ id, type, name: id, description: '', created_at: 0, updated_at: 0, config }) as HogFlow['actions'][number]

const trigger = step('trigger_node', 'trigger', { type: 'batch', filters: {} })
const email = step('email_node', 'function_email', { template_id: 'template-email', inputs: {} })
const secondEmail = step('email_node_2', 'function_email', { template_id: 'template-email', inputs: {} })
const exit = step('exit_node', 'exit', { reason: 'Default exit' })

const oneEmailFlow = {
    id: 'flow',
    name: 'Flow',
    status: 'draft',
    exit_condition: 'exit_only_at_end',
    origin_product: null,
    draft: null,
    actions: [trigger, email, exit],
    edges: [
        { from: 'trigger_node', to: 'email_node', type: 'continue' },
        { from: 'email_node', to: 'exit_node', type: 'continue' },
    ],
} as unknown as HogFlow

describe('workflowBroadcastMoveLogic', () => {
    it.each([
        ['a workflow that sends one email to a batch audience', {}, true],
        ['a broadcast already', { origin_product: 'broadcasts' }, false],
        ['a loop', { origin_product: 'loops' }, false],
        ['an archived workflow', { status: 'archived' }, false],
        ['a workflow with a staged draft', { draft: { name: 'Next' } }, false],
        ['a workflow that exits on a condition', { exit_condition: 'exit_on_conversion' }, false],
        [
            'a workflow with a second email',
            {
                actions: [trigger, email, secondEmail, exit],
                edges: [
                    { from: 'trigger_node', to: 'email_node', type: 'continue' },
                    { from: 'email_node', to: 'email_node_2', type: 'continue' },
                    { from: 'email_node_2', to: 'exit_node', type: 'continue' },
                ],
            },
            false,
        ],
        [
            'an event-triggered workflow',
            { actions: [step('trigger_node', 'trigger', { type: 'event', filters: {} }), email, exit] },
            false,
        ],
    ])('canMoveToBroadcasts: %s', (_name, overrides, expected) => {
        expect(canMoveToBroadcasts({ ...oneEmailFlow, ...overrides } as HogFlow)).toBe(expected)
    })

    describe('moving to broadcasts', () => {
        let release: ((status: number) => void) | undefined

        beforeEach(() => {
            release = undefined
            useMocks({
                post: {
                    '/api/projects/:team_id/hog_flows/:id/convert_to_broadcast/': () =>
                        new Promise((resolve) => {
                            release = (status) => resolve([status, status === 200 ? { id: 'flow' } : {}])
                        }),
                },
            })
            initKeaTests()
            router.actions.push(urls.workflow('flow', 'workflow'))
            lemonToast.dismiss()
            render(createElement(jest.requireActual('react-toastify').ToastContainer))
        })

        const moveAndRespond = async (status: number): Promise<ReturnType<typeof workflowBroadcastMoveLogic.build>> => {
            const logic = workflowBroadcastMoveLogic({ id: 'flow' })
            logic.mount()
            logic.actions.moveToBroadcasts()
            expect(logic.values.moving).toBe(true)
            await waitFor(() => expect(release).toBeTruthy())
            await act(async () => release?.(status))
            return logic
        }

        it('opens the broadcast once the move lands', async () => {
            await moveAndRespond(200)

            expect(await screen.findByText('Moved to broadcasts')).toBeTruthy()
            expect(router.values.location.pathname).toMatch(new RegExp(`${urls.broadcast('flow')}$`))
        })

        it('stays on the workflow and lets the person retry when the move fails', async () => {
            const logic = await moveAndRespond(500)

            expect(await screen.findByText(/Couldn't move this workflow to broadcasts/)).toBeTruthy()
            expect(logic.values.moving).toBe(false)
            expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflow('flow', 'workflow')}$`))
        })
    })
})
