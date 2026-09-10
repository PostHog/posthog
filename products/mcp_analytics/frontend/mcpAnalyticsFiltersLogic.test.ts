import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { MCP_ANALYTICS_FILTER_ROUTES, mcpAnalyticsFiltersLogic } from './mcpAnalyticsFiltersLogic'

const EVENT_FILTER: AnyPropertyFilter = {
    key: '$mcp_tool_name',
    value: ['create_insight'],
    operator: PropertyOperator.Exact,
    type: PropertyFilterType.Event,
}

describe('mcpAnalyticsFiltersLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('syncs property filters to the URL and clears the param when emptied', async () => {
        router.actions.push(urls.mcpAnalyticsDashboard())
        const logic = mcpAnalyticsFiltersLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setPropertyFilters([EVENT_FILTER])
        }).toFinishAllListeners()
        expect(router.values.searchParams.properties).toEqual([EVENT_FILTER])

        await expectLogic(logic, () => {
            logic.actions.setPropertyFilters([])
        }).toFinishAllListeners()
        expect(router.values.searchParams.properties).toBeUndefined()
    })

    it('keeps an explicit test-account override in the URL and drops it when following the team default', async () => {
        router.actions.push(urls.mcpAnalyticsDashboard())
        const logic = mcpAnalyticsFiltersLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setFilterTestAccounts(false)
        }).toFinishAllListeners()
        expect(router.values.searchParams.filter_test_accounts).toBe(false)

        await expectLogic(logic, () => {
            logic.actions.setFilterTestAccounts(null)
        }).toFinishAllListeners()
        expect(router.values.searchParams.filter_test_accounts).toBeUndefined()
    })

    it.each(MCP_ANALYTICS_FILTER_ROUTES.map((route) => [route.replace(':toolName', 'create_insight')]))(
        'hydrates the filters from the URL on %s',
        async (route) => {
            router.actions.push(route, { properties: [EVENT_FILTER], filter_test_accounts: true })
            const logic = mcpAnalyticsFiltersLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.propertyFilters).toEqual([EVENT_FILTER])
            expect(logic.values.filterTestAccounts).toBe(true)
        }
    )

    it('follows the team test_account_filters_default_checked setting until the user toggles', async () => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, test_account_filters_default_checked: true })
        router.actions.push(urls.mcpAnalyticsDashboard())
        const logic = mcpAnalyticsFiltersLogic()
        logic.mount()

        expect(logic.values.filterTestAccounts).toBe(true)
        logic.actions.setFilterTestAccounts(false)
        expect(logic.values.filterTestAccounts).toBe(false)
    })
})
