import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { cohortsFromSelectionCreate } from 'products/cohorts/frontend/generated/api'
import { hogFlowsRetrieve, hogFlowsRunCreate } from 'products/workflows/frontend/generated/api'

import { NotebookAppSubmission } from './NotebookAppSubmission'
import { notebookAppSubmissionLogic } from './notebookAppSubmissionLogic'

jest.mock('products/cohorts/frontend/generated/api', () => ({ cohortsFromSelectionCreate: jest.fn() }))
jest.mock('products/workflows/frontend/generated/api', () => ({
    hogFlowsRetrieve: jest.fn(),
    hogFlowsRunCreate: jest.fn(),
}))

const person = '00000000-0000-4000-8000-000000000001'
const workflowDefaults =
    jest.mocked<
        (
            ...args: Parameters<typeof hogFlowsRetrieve>
        ) => Promise<Pick<Awaited<ReturnType<typeof hogFlowsRetrieve>>, 'variables'>>
    >(hogFlowsRetrieve)
const props = {
    sessionId: 'viewer',
    draftKey: 'result-block-1',
    project: '2',
    columns: ['person_id', 'next_step'],
    rows: [[person, 'Invite a teammate']],
}
let unmountViewer: () => void
beforeEach(() => {
    initKeaTests()
    unmountViewer = notebookAppSubmissionLogic({ sessionId: props.sessionId }).mount()
    workflowDefaults.mockResolvedValue({ variables: [] })
})
afterEach(() => {
    cleanup()
    unmountViewer()
    jest.clearAllMocks()
})

it('waits for fresh results and explicitly retries the same cohort submission', async () => {
    const create = jest.mocked(cohortsFromSelectionCreate)
    create.mockRejectedValueOnce(new Error('timeout')).mockResolvedValueOnce({ cohort_id: 7 })
    const form = <NotebookAppSubmission {...props} action="create_cohort" pendingInputs />
    const { rerender } = render(form)
    fireEvent.click(screen.getByLabelText('Select row 1'))
    fireEvent.change(screen.getByLabelText('Cohort name'), { target: { value: 'Follow up' } })
    fireEvent.click(screen.getByText('Create cohort'))
    expect(create).not.toHaveBeenCalled()
    rerender(<NotebookAppSubmission {...props} action="create_cohort" pendingInputs={false} />)
    fireEvent.click(screen.getByText('Create cohort'))
    await screen.findByText(/Submission failed/)
    rerender(<div>Other tab</div>)
    rerender(<NotebookAppSubmission {...props} action="create_cohort" pendingInputs={false} />)
    expect(screen.getByLabelText('Cohort name')).toHaveValue('Follow up')
    fireEvent.click(screen.getByText('Create cohort'))
    await screen.findByText('Open cohort')
    expect(create.mock.calls).toHaveLength(2)
    expect(create.mock.calls[0]).toEqual([
        '2',
        { name: 'Follow up', request_id: expect.any(String), person_ids: [person] },
    ])
    expect(create.mock.calls[1]).toEqual(create.mock.calls[0])
})

it('keeps a pending workflow submission and its completion while switching tabs', async () => {
    let complete!: (value: Awaited<ReturnType<typeof hogFlowsRunCreate>>) => void
    const run = jest.mocked(hogFlowsRunCreate).mockReturnValueOnce(
        new Promise((resolve) => {
            complete = resolve
        })
    )
    const form = <NotebookAppSubmission {...props} action="run_workflow" workflowId="workflow" pendingInputs={false} />
    const { rerender } = render(form)
    fireEvent.click(screen.getByLabelText('Select row 1'))
    fireEvent.click(screen.getByText('Run workflow'))
    await waitFor(() => expect(run).toHaveBeenCalledTimes(1))
    rerender(<div>Other tab</div>)
    rerender(form)
    fireEvent.click(screen.getByText('Run workflow'))
    expect(run).toHaveBeenCalledTimes(1)
    rerender(<div>Other tab</div>)
    complete({ status: 'queued', invocation_id: 'abc' })
    await waitFor(() =>
        expect(
            notebookAppSubmissionLogic({ sessionId: props.sessionId }).values.drafts[props.draftKey].outcome?.title
        ).toBe('View workflow runs')
    )
    rerender(form)
    expect(screen.getByText('View workflow runs')).toBeVisible()
})

it('checks the merged workflow defaults and rows using the server JSON size', async () => {
    workflowDefaults.mockResolvedValueOnce({ variables: [{ key: 'region', default: '🦔'.repeat(420) }] })
    render(<NotebookAppSubmission {...props} action="run_workflow" workflowId="workflow" pendingInputs={false} />)
    fireEvent.click(screen.getByLabelText('Select row 1'))
    fireEvent.click(screen.getByText('Run workflow'))
    await screen.findByText(/Workflow inputs must fit within 5 KB/)
    expect(hogFlowsRunCreate).not.toHaveBeenCalled()
})

it('submits edited rows to the configured workflow only on click', async () => {
    const run = jest.mocked(hogFlowsRunCreate).mockResolvedValueOnce({ status: 'queued', invocation_id: 'abc' })
    render(<NotebookAppSubmission {...props} action="run_workflow" workflowId="workflow" pendingInputs={false} />)
    fireEvent.click(screen.getByLabelText('Select row 1'))
    fireEvent.change(screen.getByLabelText('next_step, row 1'), { target: { value: 'Review first capture' } })
    expect(run).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('Run workflow'))
    await waitFor(() =>
        expect(run).toHaveBeenCalledWith(
            '2',
            'workflow',
            { variables: { rows: [{ person_id: person, next_step: 'Review first capture' }] } },
            { headers: { 'Idempotency-Key': expect.any(String) } }
        )
    )
    await screen.findByText('View workflow runs')
})
