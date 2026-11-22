import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { setupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { eventDefinitionsList } from 'products/event_definitions/frontend/generated/api'

import { webAnalyticsSetupDetection } from './webAnalyticsSetupDetection'

jest.mock('products/event_definitions/frontend/generated/api', () => ({ eventDefinitionsList: jest.fn() }))

describe('webAnalyticsSetupDetection', () => {
    it.each([
        [['$pageview'], 'has-data'],
        [['$web_vitals'], 'needs-setup'],
        [[], 'needs-setup'],
    ])('event definitions %j map to %s', async (definitions, expected) => {
        initKeaTests()
        ;(eventDefinitionsList as jest.Mock).mockResolvedValue({ results: definitions.map((name) => ({ name })) })
        setupDetectionLogic(webAnalyticsSetupDetection).mount()
        await expectLogic(setupDetectionLogic(webAnalyticsSetupDetection)).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.WEB_ANALYTICS }).values.status).toBe(expected)
    })
})
