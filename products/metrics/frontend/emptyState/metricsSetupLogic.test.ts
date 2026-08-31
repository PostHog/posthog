import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { metricsHasMetricsRetrieve } from '../generated/api'
import { canViewMetrics } from '../metricsAccess'
import { metricsSetupLogic } from './metricsSetupLogic'

jest.mock('../metricsAccess', () => ({ canViewMetrics: jest.fn() }))
jest.mock('../generated/api', () => ({ metricsHasMetricsRetrieve: jest.fn() }))

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
})
