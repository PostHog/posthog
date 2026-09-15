import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { metricsHasMetricsRetrieve } from '../generated/api'
import { canViewMetrics } from '../metricsAccess'
import { metricsSetupLogic } from './metricsSetupLogic'

jest.mock('../metricsAccess', () => ({ canViewMetrics: jest.fn() }))
jest.mock('../generated/api', () => ({ metricsHasMetricsRetrieve: jest.fn() }))
// Real backoff waits would put the error cases over the 5s test limit; the retry policy is not what these assert.
jest.mock('lib/utils/async', () => ({
    ...jest.requireActual('lib/utils/async'),
    retryWithBackoff: (fn: () => Promise<unknown>) => fn(),
}))

describe('metricsSetupLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    // Guards the status mapping the scene gate hangs off: treating "no access"
    // as "no metrics" would show the setup screen to viewers who simply cannot
    // run the check, and flipping the has-metrics branch would gate teams with
    // real samples.
    it.each([
        [false, undefined, 'unknown'],
        [true, true, 'has-data'],
        [true, false, 'needs-setup'],
    ])('access=%s, hasMetrics=%s maps to %s', async (access, hasMetrics, expected) => {
        ;(canViewMetrics as jest.Mock).mockReturnValue(access)
        ;(metricsHasMetricsRetrieve as jest.Mock).mockResolvedValue({ hasMetrics })
        metricsSetupLogic.mount()
        await expectLogic(metricsSetupLogic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.METRICS }).values.status).toBe(expected)
    })

    it('treats a flag-gated 403 as unknown, so a fresh alpha enrollment never surfaces an error', async () => {
        // The enrollment person property takes seconds to ingest after the user turns the
        // preview on; until then the API denies with the feature_flag_required code. That
        // window is not a detection failure, and the poll answers properly once it closes.
        ;(canViewMetrics as jest.Mock).mockReturnValue(true)
        ;(metricsHasMetricsRetrieve as jest.Mock).mockRejectedValue({ status: 403, code: 'feature_flag_required' })
        metricsSetupLogic.mount()
        await expectLogic(metricsSetupLogic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.METRICS }).values.status).toBe('unknown')
        // A clean `unknown` answer, not a detection failure: the loader's failure path would
        // also land on `unknown`, but only after filing an error.
        expect(metricsSetupLogic.values.detectedStatus).toBe('unknown')
    })

    it('still fails open on other errors', async () => {
        ;(canViewMetrics as jest.Mock).mockReturnValue(true)
        ;(metricsHasMetricsRetrieve as jest.Mock).mockRejectedValue(new Error('network down'))
        metricsSetupLogic.mount()
        await expectLogic(metricsSetupLogic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.METRICS }).values.status).toBe('unknown')
    })
})
