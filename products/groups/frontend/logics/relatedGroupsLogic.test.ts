import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { relatedGroupsLogic } from './relatedGroupsLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { info: jest.fn(), error: jest.fn(), warning: jest.fn(), success: jest.fn() },
}))

describe('relatedGroupsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.mocked(lemonToast.error).mockClear()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('does not show an error toast when the request fails after unmount', async () => {
        let failRequest: () => void = () => {}
        jest.spyOn(api, 'get').mockImplementation(
            (_url, options) =>
                new Promise((_resolve, reject) => {
                    options?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
                    failRequest = () => reject({ status: 500, detail: 'Query exceeded the memory limit' })
                })
        )

        const logic = relatedGroupsLogic({ groupTypeIndex: null, id: 'person-uuid' })
        logic.mount()
        logic.unmount()
        failRequest()
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(lemonToast.error).not.toHaveBeenCalled()
    })
})
