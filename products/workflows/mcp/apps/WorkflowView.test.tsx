import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import ELK from 'elkjs/lib/elk.bundled.js'
import { type ReactElement } from 'react'

import type { HogFlowActionApi, HogFlowEdgeApi } from '../../frontend/generated/api.schemas'
import { type WorkflowData, WorkflowView } from './WorkflowView'

jest.mock(
    '@posthog/quill',
    () => ({
        Badge: ({ children }: { children: ReactElement }): ReactElement => <span>{children}</span>,
    }),
    { virtual: true }
)

const actions = [
    {
        id: 'trigger',
        name: 'When someone signs up',
        type: 'trigger',
        config: { type: 'event', filters: { events: [{ id: 'user signed up', name: 'user signed up' }] } },
    },
    {
        id: 'split',
        name: 'Came from an ad?',
        type: 'conditional_branch',
        config: { conditions: [{ name: 'Signed up from an ad', filters: { properties: [] } }] },
    },
    {
        id: 'email',
        name: 'Send the ad welcome email',
        type: 'function_email',
        config: { template_id: 'template-email', inputs: {} },
    },
    { id: 'exit', name: 'Done', type: 'exit', config: { reason: 'Onboarding sent' } },
] as unknown as HogFlowActionApi[]

const edges: HogFlowEdgeApi[] = [
    { from: 'trigger', to: 'split', type: 'continue' },
    { from: 'split', to: 'email', type: 'branch', index: 0 },
    { from: 'split', to: 'exit', type: 'continue' },
    { from: 'email', to: 'exit', type: 'continue' },
]

const workflow: WorkflowData = {
    id: 'wf-1',
    name: 'Ad sign-up onboarding',
    status: 'draft',
    version: 1,
    created_at: '2026-10-01T09:00:00Z',
    actions,
    edges,
}

/** React reads a pointer move from the change in screen position, so one event alone never counts as a move. */
function pointAt(element: HTMLElement): void {
    fireEvent.mouseMove(element, { screenX: 10 })
    fireEvent.mouseMove(element, { screenX: 20 })
}

describe('WorkflowView', () => {
    afterEach(cleanup)

    it('draws every step and names the paths of a split', async () => {
        render(<WorkflowView workflow={workflow} />)

        expect(await screen.findByText('Signed up from an ad')).toBeTruthy()
        expect(screen.getByText('No match')).toBeTruthy()
        expect(screen.getByText('When someone signs up')).toBeTruthy()
        expect(screen.getByText('Came from an ad?')).toBeTruthy()
        expect(screen.getByText('Send the ad welcome email')).toBeTruthy()
    })

    it('expands a step on click and collapses it on a second click', async () => {
        render(<WorkflowView workflow={workflow} />)
        const step = await screen.findByLabelText('Done')

        fireEvent.click(step)
        expect(step.getAttribute('aria-expanded')).toBe('true')
        expect(screen.getByText('Click to collapse the step')).toBeTruthy()

        fireEvent.click(step)
        expect(step.getAttribute('aria-expanded')).toBe('false')
    })

    it('keeps the card closed after a quick expand and collapse under a pointer that has not left', async () => {
        jest.useFakeTimers()
        try {
            render(<WorkflowView workflow={workflow} />)
            const done = await screen.findByLabelText('Done')

            pointAt(done)
            fireEvent.click(done)
            fireEvent.click(done)
            act(() => jest.runOnlyPendingTimers())

            expect(screen.queryByText('Click to expand the step')).toBeNull()
        } finally {
            jest.useRealTimers()
        }
    })

    it('opens the card on hover for a step that collapsed while the pointer was elsewhere', async () => {
        jest.useFakeTimers()
        try {
            render(<WorkflowView workflow={workflow} />)
            const done = await screen.findByLabelText('Done')
            const email = screen.getByLabelText('Send the ad welcome email')

            fireEvent.click(done)
            fireEvent.mouseLeave(done)
            fireEvent.click(email)
            pointAt(done)
            act(() => jest.runOnlyPendingTimers())

            expect(screen.getByText('Click to expand the step')).toBeTruthy()
        } finally {
            jest.useRealTimers()
        }
    })

    it('draws the staged changes of an active workflow and marks them unpublished', async () => {
        const staged = [actions[0], { ...actions[3], name: 'Finished' }]
        const stagedEdges: HogFlowEdgeApi[] = [{ from: 'trigger', to: 'exit', type: 'continue' }]

        render(
            <WorkflowView
                workflow={{ ...workflow, status: 'active', draft: { actions: staged, edges: stagedEdges } }}
            />
        )

        expect(await screen.findByLabelText('Finished')).toBeTruthy()
        expect(screen.queryByText('Send the ad welcome email')).toBeNull()
        expect(screen.getByText('Unpublished changes')).toBeTruthy()
    })

    it('keeps the title when a step is malformed, and draws the steps again once they are fixed', async () => {
        const silenced = jest.spyOn(console, 'error').mockImplementation(() => {})
        const malformed = { id: 'wait', name: 'Wait', type: 'wait_until_condition', config: {} }

        const { rerender } = render(
            <WorkflowView workflow={{ ...workflow, actions: [...actions, malformed] as HogFlowActionApi[] }} />
        )

        expect(screen.getByText('Ad sign-up onboarding')).toBeTruthy()
        expect(screen.getByText(/The steps could not be drawn here/)).toBeTruthy()

        rerender(<WorkflowView workflow={workflow} />)

        expect(await screen.findByLabelText('Done')).toBeTruthy()
        expect(screen.queryByText(/The steps could not be drawn here/)).toBeNull()
        silenced.mockRestore()
    })

    it('draws the steps again when the next workflow after a failed layout arrives', async () => {
        const silenced = jest.spyOn(console, 'error').mockImplementation(() => {})
        jest.spyOn(ELK.prototype, 'layout').mockRejectedValueOnce(new Error('layout failed'))

        const { rerender } = render(<WorkflowView workflow={workflow} />)

        expect(await screen.findByText(/The steps could not be drawn here/)).toBeTruthy()

        rerender(<WorkflowView workflow={{ ...workflow, actions: [...actions] }} />)

        expect(await screen.findByLabelText('Done')).toBeTruthy()
        silenced.mockRestore()
    })

    it('shows only the title when the workflow has no steps', () => {
        render(<WorkflowView workflow={{ ...workflow, actions: [], edges: [] }} />)

        expect(screen.getByText('Ad sign-up onboarding')).toBeTruthy()
        expect(screen.queryByRole('button')).toBeNull()
    })
})
