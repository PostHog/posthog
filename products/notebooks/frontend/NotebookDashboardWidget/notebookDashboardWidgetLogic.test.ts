import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    notebooksRunsCreate,
    notebooksRunsRetrieve,
    notebooksWidgetSnapshotCreate,
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
    notebooksWidgetSnapshotCreate: jest.fn(),
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
            onUpdateSnapshot: update,
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
        jest.mocked(notebooksWidgetSnapshotCreate).mockImplementation(
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
        expect(update).toHaveBeenCalledWith('new')
        expect(logic.values.snapshot?.id).toBe('new')
        expect(notebooksWidgetSnapshotCreate).toHaveBeenCalledWith(expect.any(String), 'notebook', {
            node_id: 'widget',
            version_id: 'version',
            notebook_run_id: 'run',
            previous_snapshot_id: 'saved',
        })
    })

    it('resumes polling after a network error without starting another notebook run', async () => {
        jest.useFakeTimers()
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
            jest.mocked(notebooksWidgetSnapshotCreate).mockResolvedValue({ ...snapshot, id: 'new' })
            update.mockResolvedValue(undefined)
            await expectLogic(logic, () => logic.actions.refresh()).toFinishAllListeners()
            expect(logic.values.runId).toBe('run')
            expect(logic.values.error).toBe('Network unavailable')
            await expectLogic(logic, () => logic.actions.pollRun()).toFinishAllListeners()
            expect(logic.values.error).toBeNull()
            await expectLogic(logic, () => {
                jest.advanceTimersByTime(2000)
            }).toFinishAllListeners()
            expect(update).toHaveBeenCalledWith('new')
            expect(notebooksRunsCreate).toHaveBeenCalledTimes(1)
        } finally {
            jest.useRealTimers()
        }
    })

    it.each(['run', 'capture', 'save'])('keeps the previous snapshot after a failed %s', async (step) => {
        jest.mocked(notebooksRunsCreate).mockResolvedValue({ run_id: 'run' } as NotebookRunStartResponseApi)
        jest.mocked(notebooksRunsRetrieve).mockResolvedValue({
            run_id: 'run',
            status: step === 'run' ? 'failed' : 'done',
            error: step === 'run' ? 'Cell failed' : null,
        } as NotebookRunStatusResponseApi)
        jest.mocked(notebooksWidgetSnapshotCreate).mockImplementation(async () => {
            if (step === 'capture') {
                throw new Error('Results expired')
            }
            return { ...snapshot, id: 'new' }
        })
        update.mockImplementation(async () => {
            if (step === 'save') {
                throw new Error('Dashboard save failed')
            }
        })
        await expectLogic(logic, () => logic.actions.refresh()).toFinishAllListeners()
        expect(logic.values.snapshot).toEqual(snapshot)
        expect(logic.values.refreshing).toBe(false)
        expect(logic.values.error).toBeTruthy()
        if (step !== 'save') {
            expect(update).not.toHaveBeenCalled()
        }
    })
})
