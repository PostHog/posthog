import { act, renderHook, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { makeReport } from '../../__mocks__/inboxMocks'
import { SignalReportStatus } from '../../types'
import { setReportState } from '../../utils/writeTimeout'
import { useReportDetailActions } from './ReportDetailActions'

jest.mock('../../utils/writeTimeout', () => ({
    ...jest.requireActual('../../utils/writeTimeout'),
    setReportState: jest.fn(),
}))

describe('useReportDetailActions', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('leaves a deep-linked report for the list before the restore write settles', async () => {
        let finishWrite: () => void = () => {}
        jest.mocked(setReportState).mockReturnValue(
            new Promise((resolve) => {
                finishWrite = () => resolve({} as Awaited<ReturnType<typeof setReportState>>)
            })
        )
        const toastSuccess = jest.spyOn(lemonToast, 'success').mockImplementation(() => 'toast')
        const report = makeReport({
            id: 'report-1',
            status: SignalReportStatus.SUPPRESSED,
            suppression_source: 'dismissed',
        })

        const { result } = renderHook(() => useReportDetailActions(report))
        const restore = result.current.find((action) => action.key === 'restore')
        act(() => restore!.onClick({} as any))

        expect(router.values.location.pathname).toMatch(/\/inbox(\/[^/]+)?$/)
        expect(toastSuccess).not.toHaveBeenCalled()

        await act(async () => finishWrite())
        await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('Report restored to inbox'))
    })
})
