import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { bulkScanLogic } from './bulkScanLogic'

describe('bulkScanLogic', () => {
    let logic: ReturnType<typeof bulkScanLogic.build>
    let observeSpy: jest.Mock
    let successToast: jest.SpyInstance
    let errorToast: jest.SpyInstance

    const sessionIds = (n: number): string[] => Array.from({ length: n }, (_, i) => `session-${i + 1}`)

    beforeEach(() => {
        observeSpy = jest.fn(() => [202, { workflow_id: 'wf-test' }])
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': {
                    results: [{ id: 'scanner-1', name: 'Rage detector' }],
                    count: 1,
                    next: null,
                },
            },
            post: {
                '/api/projects/:team/vision/scanners/:id/observe/': observeSpy,
            },
        })
        initKeaTests()
        successToast = jest.spyOn(lemonToast, 'success').mockImplementation(() => 'toast-id')
        errorToast = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')
        logic = bulkScanLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('scans every selected recording and toasts the started count with the scanner name', async () => {
        await expectLogic(logic, () => logic.actions.scanRecordings('scanner-1', sessionIds(3)))
            .toDispatchActions(['scanRecordings', 'scanRecordingsSuccess'])
            .toMatchValues({ scanning: false })
        expect(observeSpy).toHaveBeenCalledTimes(3)
        expect(successToast.mock.calls[0][0]).toContain('Started scanning 3 recordings with “Rage detector”')
        expect(errorToast).not.toHaveBeenCalled()
    })

    it('stops after the batch that hits a 402 and reports the skipped remainder', async () => {
        observeSpy.mockImplementation(() =>
            observeSpy.mock.calls.length === 10
                ? [402, { detail: 'Monthly quota reached.' }]
                : [202, { workflow_id: 'wf-test' }]
        )
        await expectLogic(logic, () => logic.actions.scanRecordings('scanner-1', sessionIds(25)))
            .toDispatchActions(['scanRecordingsSuccess'])
            .toMatchValues({ scanning: false })
        // Only the first batch of 10 fires; the remaining 15 are skipped, not attempted.
        expect(observeSpy).toHaveBeenCalledTimes(10)
        expect(successToast.mock.calls[0][0]).toContain('Started scanning 9 recordings')
        expect(errorToast.mock.calls[0][0]).toBe('Monthly quota reached. Skipped 15 remaining recordings.')
    })

    it('continues through all batches on non-quota failures and surfaces the first error detail', async () => {
        observeSpy.mockImplementation(() => [500, { detail: 'boom' }])
        await expectLogic(logic, () => logic.actions.scanRecordings('scanner-1', sessionIds(12)))
            .toDispatchActions(['scanRecordingsSuccess'])
            .toMatchValues({ scanning: false })
        expect(observeSpy).toHaveBeenCalledTimes(12)
        expect(successToast).not.toHaveBeenCalled()
        expect(errorToast.mock.calls[0][0]).toBe('Failed to start scanning 12 recordings: boom')
    })

    it('rejects an empty selection without any requests', async () => {
        await expectLogic(logic, () => logic.actions.scanRecordings('scanner-1', []))
            .toDispatchActions(['scanRecordingsFailure'])
            .toMatchValues({ scanning: false })
        expect(observeSpy).not.toHaveBeenCalled()
        expect(errorToast.mock.calls[0][0]).toBe('Select at least one recording to scan')
    })
})
