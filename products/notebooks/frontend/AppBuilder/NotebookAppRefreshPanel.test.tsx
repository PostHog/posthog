import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { ApiConfig } from 'lib/api'

import * as notebookApi from '../generated/api'
import { NotebookAppRefreshPanel } from './NotebookAppRefreshPanel'

const status = {
    checked_node_ids: [],
    check_targets: [],
    published_revision: 4,
    revision: 4,
    enabled: true,
    interval_minutes: 60,
    freshness_minutes: 90,
    last_success_at: '2026-01-01T15:00:00Z',
    history: [
        {
            due_at: '2026-01-01T14:59:00Z',
            finished_at: '2026-01-01T15:00:00Z',
            revision: 4,
            status: 'succeeded',
            detail: '',
            output_count: 1,
            checked_count: 0,
            duration_seconds: 60,
        },
    ],
}

describe('notebook app refresh panel', () => {
    beforeEach(() => jest.spyOn(ApiConfig, 'getCurrentTeamId').mockReturnValue(1))
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('retries the original schedule write', async () => {
        jest.spyOn(notebookApi, 'notebooksAppRefreshStatusRetrieve').mockResolvedValue(status)
        const save = jest
            .spyOn(notebookApi, 'notebooksAppRefreshScheduleCreate')
            .mockRejectedValueOnce(new Error('unavailable'))
            .mockResolvedValue(status)
        render(<NotebookAppRefreshPanel shortId="plan" revision={4} editable />)
        fireEvent.click(await screen.findByText('Scheduled refresh'))
        fireEvent.click(screen.getByText('Save schedule'))
        fireEvent.click((await screen.findAllByRole('button', { name: 'Retry' }))[0])
        await waitFor(() => expect(save).toHaveBeenCalledTimes(2))
        expect(save.mock.calls[1]).toEqual(save.mock.calls[0])
    })

    it('keeps an authorized snapshot on an error and identifies the published fallback when scopes differ', async () => {
        const getStatus = jest.spyOn(notebookApi, 'notebooksAppRefreshStatusRetrieve').mockResolvedValue(status)
        const rows = { metric: { results: [[42]], columns: ['count'] } }
        const outputs = jest
            .spyOn(notebookApi, 'notebooksAppRefreshOutputsRetrieve')
            .mockResolvedValueOnce({ revision: 4, outputs: rows })
            .mockResolvedValue({ revision: 4, outputs: {} })
        const onOutputs = jest.fn()
        render(<NotebookAppRefreshPanel shortId="plan" revision={4} onOutputs={onOutputs} />)
        await screen.findByText('Fresh')
        expect(onOutputs).toHaveBeenLastCalledWith(rows)
        fireEvent.click(screen.getByText('Scheduled refresh'))
        getStatus.mockRejectedValueOnce(new Error('unavailable'))
        fireEvent.click(screen.getByText('Check status'))
        await screen.findAllByRole('button', { name: 'Retry' })
        expect(onOutputs).toHaveBeenLastCalledWith(rows)
        fireEvent.click(screen.getAllByRole('button', { name: 'Retry' })[0])
        await screen.findByText('Published results')
        expect(outputs).toHaveBeenCalledTimes(2)
        expect(onOutputs).toHaveBeenLastCalledWith({})
    })
})
