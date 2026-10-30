import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { eventDefinitionsList } from 'products/event_definitions/frontend/generated/api'

import { webAnalyticsSetupLogic } from './webAnalyticsSetupLogic'

jest.mock('products/event_definitions/frontend/generated/api', () => ({ eventDefinitionsList: jest.fn() }))

describe('webAnalyticsSetupLogic', () => {
    it.each([
        [['$pageview'], 'has-data'],
        [['$web_vitals'], 'needs-setup'],
        [[], 'needs-setup'],
    ])('event definitions %j map to %s', async (definitions, expected) => {
        initKeaTests()
        ;(eventDefinitionsList as jest.Mock).mockResolvedValue({ results: definitions.map((name) => ({ name })) })
        webAnalyticsSetupLogic.mount()
        await expectLogic(webAnalyticsSetupLogic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.WEB_ANALYTICS }).values.status).toBe(expected)
    })
})
