import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { surveysList } from '../generated/api'
import { surveysSetupLogic } from './surveysSetupLogic'

jest.mock('../generated/api', () => ({ surveysList: jest.fn() }))

describe('surveysSetupLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    // Guards the count mapping the scene gate hangs off. The archived case matters:
    // the list excludes archived surveys unless asked, so collapsing to one query
    // would gate a project that archived all of its surveys.
    it.each([
        [0, 0, 'needs-setup'],
        [2, 0, 'has-data'],
        [0, 1, 'has-data'],
    ])('live=%s, archived=%s maps to %s', async (live, archived, expected) => {
        ;(surveysList as jest.Mock).mockImplementation((_projectId: string, params?: { archived?: boolean }) =>
            Promise.resolve({ count: params?.archived ? archived : live, results: [] })
        )
        surveysSetupLogic.mount()
        await expectLogic(surveysSetupLogic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.SURVEYS }).values.status).toBe(expected)
    })
})
