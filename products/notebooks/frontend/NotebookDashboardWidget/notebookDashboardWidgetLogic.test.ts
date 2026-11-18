import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import {
    notebooksRunsCreate,
    notebooksRunsRetrieve,
    notebooksWidgetSnapshotPublish,
    notebooksWidgetSnapshotRetrieve,
} from '../generated/api'
import type {
    NotebookRunStartResponseApi,
    NotebookRunStatusResponseApi,
    WidgetSnapshotApi,
} from '../generated/api.schemas'
import { notebookDashboardWidgetLogic } from './notebookDashboardWidgetLogic'

jest.mock('../generated/api', () => ({
    notebooksRunsCreate: jest.fn(),
    notebooksRunsRetrieve: jest.fn(),
    notebooksRunsInterruptCreate: jest.fn(),
    notebooksWidgetSnapshotPublish: jest.fn(),
    notebooksWidgetSnapshotRetrieve: jest.fn(),
    notebooksWidgetSource: jest.fn(),
}))

const snapshot = {
    id: 'saved',
    node_id: 'widget',
    version_id: 'version',
    frame_names: ['revenue'],
} as WidgetSnapshotApi

describe('notebookDashboardWidgetLogic', () => {
    let logic: ReturnType<typeof notebookDashboardWidgetLogic.build>
    const update = jest.fn()
    beforeEach(async () => {
        initKeaTests()
        jest.clearAllMocks()
        jest.mocked(notebooksWidgetSnapshotRetrieve).mockResolvedValue(snapshot)
        logic = notebookDashboardWidgetLogic({
            tileId: 1,
            notebookShortId: 'notebook',
            snapshotId: snapshot.id,
            onSnapshotPublished: update,
        })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
    })
    afterEach(() => logic.unmount())

    it('opens saved results without starting compute and replaces them only after a successful run and save', async () => {
        expect(logic.values.snapshot).toEqual(snapshot)
        expect(notebooksRunsCreate).not.toHaveBeenCalled()
        jest.mocked(notebooksRunsCreate).mockResolvedValue({ run_id: 'run' } as NotebookRunStartResponseApi)
        jest.mocked(notebooksRunsRetrieve).mockResolvedValue({
            run_id: 'run',
            status: 'done',
        } as NotebookRunStatusResponseApi)
        let finishCapture!: (saved: WidgetSnapshotApi) => void
        let captureStarted!: () => void
        const started = new Promise<void>((resolve) => {
            captureStarted = resolve
        })
        jest.mocked(notebooksWidgetSnapshotPublish).mockImplementation(
            () =>
                new Promise((resolve) => {
                    finishCapture = resolve
                    captureStarted()
                })
        )
        logic.actions.refresh()
        logic.actions.refresh()
        await started
        expect(logic.values.snapshot).toEqual(snapshot)
        expect(update).not.toHaveBeenCalled()
        expect(notebooksRunsCreate).toHaveBeenCalledTimes(1)
        await expectLogic(logic, () => finishCapture({ ...snapshot, id: 'new' })).toFinishAllListeners()
        expect(update).toHaveBeenCalledTimes(1)
        expect(logic.values.snapshot?.id).toBe('new')
        expect(notebooksWidgetSnapshotPublish).toHaveBeenCalledWith(expect.any(String), 'notebook', {
            node_id: 'widget',
            version_id: 'version',
            notebook_run_id: 'run',
            previous_snapshot_id: 'saved',
            tile_id: 1,
        })
    })

    it.each([false, true])('resumes polling after a network error when hidden=%s', async (hidden) => {
        jest.useFakeTimers()
        const hiddenSpy = jest.spyOn(document, 'hidden', 'get').mockReturnValue(hidden)
        document.dispatchEvent(new Event('visibilitychange'))
        try {
            jest.mocked(notebooksRunsCreate).mockResolvedValue({ run_id: 'run' } as NotebookRunStartResponseApi)
            jest.mocked(notebooksRunsRetrieve)
                .mockRejectedValueOnce(new Error('Network unavailable'))
                .mockResolvedValueOnce({
                    run_id: 'run',
                    status: 'running',
                    current_index: 0,
                    cell_count: 1,
                } as NotebookRunStatusResponseApi)
                .mockResolvedValue({ run_id: 'run', status: 'done' } as NotebookRunStatusResponseApi)
            jest.mocked(notebooksWidgetSnapshotPublish).mockResolvedValue({ ...snapshot, id: 'new' })
            update.mockResolvedValue(undefined)
            await expectLogic(logic, () => logic.actions.refresh()).toFinishAllListeners()
            expect(logic.values.runId).toBe('run')
            expect(logic.values.error).toBe('Network unavailable')
            await expectLogic(logic, () => logic.actions.pollRun()).toFinishAllListeners()
            expect(logic.values.error).toBeNull()
            await expectLogic(logic, () => {
                jest.advanceTimersByTime(2000)
            }).toFinishAllListeners()
            expect(update).toHaveBeenCalledTimes(1)
            expect(notebooksRunsCreate).toHaveBeenCalledTimes(1)
        } finally {
            hiddenSpy.mockRestore()
            document.dispatchEvent(new Event('visibilitychange'))
            jest.useRealTimers()
        }
    })

    it.each([
        [
            new ApiError('Conflict', 409, undefined, { detail: 'Refresh this widget from the notebook.' }),
            'Refresh this widget from the notebook.',
        ],
        [new Error('Network error'), 'Could not load the saved results. Check your notebook access and try again.'],
    ])('shows the API detail or a fallback when saved results cannot load', async (error, message) => {
        jest.mocked(notebooksWidgetSnapshotRetrieve).mockRejectedValueOnce(error)
        await expectLogic(logic, () => logic.actions.loadSnapshot()).toFinishAllListeners()
        expect(logic.values.error).toBe(message)
    })

    it.each(['run', 'publish'])('keeps the previous snapshot after a failed %s', async (step) => {
        jest.mocked(notebooksRunsCreate).mockResolvedValue({ run_id: 'run' } as NotebookRunStartResponseApi)
        jest.mocked(notebooksRunsRetrieve).mockResolvedValue({
            run_id: 'run',
            status: step === 'run' ? 'failed' : 'done',
            error: step === 'run' ? 'Cell failed' : null,
        } as NotebookRunStatusResponseApi)
        jest.mocked(notebooksWidgetSnapshotPublish).mockImplementation(async () => {
            if (step === 'publish') {
                throw new Error('Results expired')
            }
            return { ...snapshot, id: 'new' }
        })
        await expectLogic(logic, () => logic.actions.refresh()).toFinishAllListeners()
        expect(logic.values.snapshot).toEqual(snapshot)
        expect(logic.values.refreshing).toBe(false)
        expect(logic.values.error).toBeTruthy()
        expect(update).not.toHaveBeenCalled()
    })
})
