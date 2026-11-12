import { expectLogic } from 'kea-test-utils'

import { handleApprovalRequired } from 'lib/approvals/utils'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { featureFlagsVersionsRestoreCreate, featureFlagsVersionsRetrieve } from '../generated/api'
import { featureFlagRestoreVersionLogic } from './featureFlagRestoreVersionLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    featureFlagsVersionsRetrieve: jest.fn(),
    featureFlagsVersionsRestoreCreate: jest.fn(),
}))
jest.mock('lib/approvals/utils')

const FLAG_ID = 7
const STALE_MESSAGE = 'This flag changed while you were reviewing the restore. Review the history and try again.'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve: (value: T) => void = () => {}
    const promise = new Promise<T>((r) => {
        resolve = r
    })
    return { promise, resolve }
}

describe('featureFlagRestoreVersionLogic', () => {
    let logic: ReturnType<typeof featureFlagRestoreVersionLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        jest.spyOn(lemonToast, 'error').mockImplementation(() => '')
        jest.spyOn(lemonToast, 'success').mockImplementation(() => '')
        jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        useMocks({
            get: {
                [`/api/projects/:team_id/feature_flags/${FLAG_ID}/`]: () => [
                    200,
                    { id: FLAG_ID, key: 'checkout', version: 3, filters: { groups: [] } },
                ],
            },
        })
        initKeaTests()
        logic = featureFlagRestoreVersionLogic({ flagId: FLAG_ID })
        logic.mount()
    })

    afterEach(() => {
        if (logic.isMounted()) {
            logic.unmount()
        }
    })

    it.each([
        {
            name: 'approval required',
            error: { status: 409, data: { change_request_id: 'cr-1' } },
            approvalHandled: true,
            staleToast: false,
        },
        { name: 'stale version', error: { status: 409, data: {} }, approvalHandled: false, staleToast: true },
    ])('a $name 409 goes to its own handler', async ({ error, approvalHandled, staleToast }) => {
        jest.mocked(featureFlagsVersionsRestoreCreate).mockRejectedValue(error)

        await expectLogic(logic, () => logic.actions.confirmRestoreVersion(1, 3))
            .toFinishAllListeners()
            .toMatchValues({ busyVersion: null })

        expect(jest.mocked(handleApprovalRequired).mock.calls.length > 0).toBe(approvalHandled)
        expect(jest.mocked(lemonToast.error).mock.calls.some(([message]) => message === STALE_MESSAGE)).toBe(staleToast)
    })

    it('sends one restore while one is in flight', async () => {
        const request = deferred<any>()
        jest.mocked(featureFlagsVersionsRestoreCreate).mockReturnValue(request.promise)

        logic.actions.confirmRestoreVersion(1, 3)
        logic.actions.confirmRestoreVersion(1, 3)
        request.resolve({})

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ busyVersion: null })
        expect(featureFlagsVersionsRestoreCreate).toHaveBeenCalledTimes(1)
    })

    it('opens no preview after the flag page unmounts', async () => {
        const request = deferred<any>()
        jest.mocked(featureFlagsVersionsRetrieve).mockReturnValue(request.promise)

        logic.actions.restoreVersion(1)
        logic.unmount()
        request.resolve({ version: 1, filters: { groups: [] } })
        await request.promise
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(LemonDialog.open).not.toHaveBeenCalled()
        expect(lemonToast.error).not.toHaveBeenCalled()
    })
})
