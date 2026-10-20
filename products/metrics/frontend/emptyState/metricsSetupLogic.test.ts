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
        initKeaTests()
    })

    // Guards the status mapping the empty state hangs off: treating "no access"
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

    it('still fails open on other errors', async () => {
        ;(canViewMetrics as jest.Mock).mockReturnValue(true)
        ;(metricsHasMetricsRetrieve as jest.Mock).mockRejectedValue(new Error('network down'))
        metricsSetupLogic.mount()
        await expectLogic(metricsSetupLogic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.METRICS }).values.status).toBe('unknown')
    })
})
