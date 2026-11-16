import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    confirmArchiveWorkflow,
    confirmDeleteWorkflow,
    restoreWorkflowToDraft,
    setWorkflowStatus,
} from './workflowRowActions'

const { ToastContainer, toast } = jest.requireActual('react-toastify')

// A child environment's team id differs from its project id; these calls address the team.
const TEAM_ID = '4242'
const UPDATED_AT = '2026-09-27T12:00:00Z'

interface RowState {
    pending: boolean
    status: string | null
}

describe('workflowRowActions', () => {
    let requests: { method: string; path: string; body?: unknown }[]
    let serverAnswers: Promise<void>

    beforeEach(() => {
        requests = []
        serverAnswers = Promise.resolve()
        const respond = async ({
            request,
            params,
        }: {
            request: Request
            params: Record<string, unknown>
        }): Promise<[number, unknown?]> => {
            const body = request.method === 'PATCH' ? await request.json() : undefined
            requests.push({ method: request.method, path: new URL(request.url).pathname, body })
            await serverAnswers
            if (params.id === 'wf-broken') {
                return [500, { detail: 'Server error' }]
            }
            return request.method === 'DELETE' ? [204] : [200, { ...(body as object), updated_at: UPDATED_AT }]
        }
        useMocks({
            patch: { '/api/projects/:team_id/hog_flows/:id/': respond },
            delete: { '/api/projects/:team_id/hog_flows/:id/': respond },
        })
        initKeaTests()
        render(<ToastContainer />)
    })

    afterEach(() => {
        cleanup()
        toast.dismiss()
        document.body.innerHTML = ''
    })

    const confirmIn = async (button: string): Promise<void> => {
        await act(async () => {
            fireEvent.click(screen.getByText(button).closest('button') as HTMLElement)
        })
    }

    it.each([
        [
            'restores a workflow to draft',
            () => restoreWorkflowToDraft(TEAM_ID, { id: 'wf-1', name: 'Welcome' }),
            'draft',
        ],
        ['sets a status', () => setWorkflowStatus(TEAM_ID, { id: 'wf-1', name: 'Welcome' }, 'active'), 'active'],
    ])('%s through the team-scoped endpoint', async (_, run, status) => {
        await expect(run()).resolves.toEqual({ status, updated_at: UPDATED_AT })
        expect(requests).toEqual([
            { method: 'PATCH', path: `/api/projects/${TEAM_ID}/hog_flows/wf-1/`, body: { status } },
        ])
    })

    it.each([
        [
            'restore',
            () => restoreWorkflowToDraft(TEAM_ID, { id: 'wf-broken', name: 'Broken' }),
            'Failed to restore workflow: Server error',
        ],
        [
            'status change',
            () => setWorkflowStatus(TEAM_ID, { id: 'wf-broken', name: 'Broken' }, 'active'),
            'Failed to update workflow: Server error',
        ],
    ])('shows why a failed %s failed and leaves the caller to keep its row', async (_, run, message) => {
        await expect(run()).resolves.toBeNull()
        expect(await screen.findByText(message)).toBeInTheDocument()
    })

    it.each([
        [
            'archive',
            (row: RowState) =>
                confirmArchiveWorkflow(
                    TEAM_ID,
                    { id: 'wf-1', name: 'Welcome', status: 'active' },
                    (updated) => (row.status = updated.status ?? null),
                    (pending) => (row.pending = pending)
                ),
            'Are you sure you want to archive "Welcome"? In-progress workflow invocations will end without completing.',
            { method: 'PATCH', path: `/api/projects/${TEAM_ID}/hog_flows/wf-1/`, body: { status: 'archived' } },
            'archived',
            'Workflow "Welcome" archived',
        ],
        [
            'delete',
            (row: RowState) =>
                confirmDeleteWorkflow(
                    TEAM_ID,
                    { id: 'wf-1', name: 'Welcome', status: 'active' },
                    () => (row.status = null),
                    (pending) => (row.pending = pending)
                ),
            'Are you sure you want to permanently delete "Welcome"? This action cannot be undone.',
            { method: 'DELETE', path: `/api/projects/${TEAM_ID}/hog_flows/wf-1/`, body: undefined },
            null,
            'Workflow "Welcome" deleted',
        ],
    ])(
        'confirming the %s dialog keeps the row busy until the server answers, then updates it',
        async (verb, open, question, request, finalStatus, toast) => {
            let answer = (): void => {}
            serverAnswers = new Promise((resolve) => (answer = resolve))
            const row: RowState = { pending: false, status: 'active' }

            act(() => open(row))
            expect(await screen.findByText(question)).toBeInTheDocument()
            expect(requests).toEqual([])

            await confirmIn(verb === 'archive' ? 'Archive' : 'Delete')
            await waitFor(() => expect(requests).toEqual([request]))
            expect(row).toEqual({ pending: true, status: 'active' })

            answer()
            await waitFor(() => expect(row).toEqual({ pending: false, status: finalStatus }))
            expect(await screen.findByText(toast)).toBeInTheDocument()
        }
    )

    it.each([
        [
            'archive',
            (row: RowState) =>
                confirmArchiveWorkflow(
                    TEAM_ID,
                    { id: 'wf-broken', name: 'Broken', status: 'active' },
                    (updated) => (row.status = updated.status ?? null),
                    (pending) => (row.pending = pending)
                ),
            'Archive',
            'Failed to archive workflow: Server error',
        ],
        [
            'delete',
            (row: RowState) =>
                confirmDeleteWorkflow(
                    TEAM_ID,
                    { id: 'wf-broken', name: 'Broken', status: 'active' },
                    () => (row.status = null),
                    (pending) => (row.pending = pending)
                ),
            'Delete',
            'Failed to delete workflow: Server error',
        ],
    ])('a failed %s shows the error and leaves the row as it was', async (_, open, button, message) => {
        const row: RowState = { pending: false, status: 'active' }

        act(() => open(row))
        await screen.findByText(button)
        await confirmIn(button)

        expect(await screen.findByText(message)).toBeInTheDocument()
        expect(row).toEqual({ pending: false, status: 'active' })
    })
})
