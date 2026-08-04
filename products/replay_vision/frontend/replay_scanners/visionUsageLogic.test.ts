import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { visionUsageLogic } from './visionUsageLogic'

describe('visionUsageLogic', () => {
    afterEach(() => {
        visionUsageLogic.unmount()
    })

    it('loads usage scanners on mount when the current project is available', async () => {
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': { results: [] },
            },
        })
        initKeaTests()

        const logic = visionUsageLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadUsageScanners', 'loadUsageScannersSuccess'])
    })

    it('does not request scanners when the user has no access to the current project', async () => {
        const requestSpy = jest.fn()
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/': () => {
                    requestSpy()
                    return [200, { results: [] }]
                },
            },
        })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, effective_membership_level: null })

        const logic = visionUsageLogic()
        logic.mount()

        await expectLogic(logic).toNotHaveDispatchedActions(['loadUsageScanners'])
        expect(requestSpy).not.toHaveBeenCalled()
    })
})
