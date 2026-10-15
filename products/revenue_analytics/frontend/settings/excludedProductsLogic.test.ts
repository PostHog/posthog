import externalDataSourceResponseMock from '~/mocks/fixtures/api/projects/team_id/external_data_sources/externalDataSource.json'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'
import { ExternalDataSource } from '~/types'

import { excludedProductsLogic } from './excludedProductsLogic'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))

describe('excludedProductsLogic', () => {
    let logic: ReturnType<typeof excludedProductsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.mocked(performQuery).mockResolvedValue({ results: [['prod_example', 'Example product']] })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([true, false])('loads products when enabled, starting enabled=%s', async (enabled) => {
        const source = {
            ...externalDataSourceResponseMock,
            revenue_analytics_config: { enabled, include_invoiceless_charges: true },
        } as unknown as ExternalDataSource
        logic = excludedProductsLogic({ source })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(performQuery).toHaveBeenCalledTimes(enabled ? 1 : 0)

        excludedProductsLogic({
            source: { ...source, revenue_analytics_config: { ...source.revenue_analytics_config, enabled: false } },
        })
        await expectLogic(logic, () => {
            excludedProductsLogic({
                source: { ...source, revenue_analytics_config: { ...source.revenue_analytics_config, enabled: true } },
            })
        })
            .toFinishAllListeners()
            .toMatchValues({ products: [{ id: 'prod_example', name: 'Example product' }], productsLoading: false })

        expect(performQuery).toHaveBeenCalledTimes(enabled ? 2 : 1)
    })
})
