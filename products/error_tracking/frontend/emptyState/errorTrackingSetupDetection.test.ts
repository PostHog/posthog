import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { setupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import type { TeamType } from '~/types'

import { errorTrackingSetupDetection } from './errorTrackingSetupDetection'

jest.mock('lib/api', () => ({
    ...jest.requireActual('lib/api'),
    ApiRequest: jest.fn(),
}))

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { ApiRequest } = require('lib/api')

describe('errorTrackingSetupDetection', () => {
    function mountWith(exists: boolean, autocaptureOptIn: boolean): void {
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            autocapture_exceptions_opt_in: autocaptureOptIn,
        } as TeamType)
        ;(ApiRequest as jest.Mock).mockImplementation(() => ({
            errorTrackingIssuesExists: () => ({ get: async () => ({ exists }) }),
        }))
        setupDetectionLogic(errorTrackingSetupDetection).mount()
    }

    // Guards the status mapping the scene gate hangs off: dropping the opt-in
    // branch would show "install the SDK" to already-instrumented projects, and
    // flipping the exists check would gate projects that have real issues.
    it.each([
        [true, false, 'has-data'],
        [true, true, 'has-data'],
        [false, true, 'waiting-for-data'],
        [false, false, 'needs-setup'],
    ])('exists=%s, autocapture=%s maps to %s', async (exists, autocaptureOptIn, expected) => {
        mountWith(exists, autocaptureOptIn)
        await expectLogic(setupDetectionLogic(errorTrackingSetupDetection)).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.ERROR_TRACKING }).values.status).toBe(expected)
    })
})
