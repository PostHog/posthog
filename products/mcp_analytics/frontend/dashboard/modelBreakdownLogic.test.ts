import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { HogQLFilters, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { MODEL_PAGE_SIZE, modelBreakdownLogic } from './modelBreakdownLogic'

jest.mock('lib/api')

const mockApi = api as jest.Mocked<typeof api>

describe('modelBreakdownLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it('loads individual models on expansion and preserves filters across pages', async () => {
        const filters: HogQLFilters = {
            dateRange: { date_from: '-14d' },
            filterTestAccounts: true,
            properties: [
                {
                    key: '$mcp_server_name',
                    type: PropertyFilterType.Event,
                    operator: PropertyOperator.Exact,
                    value: ['example-server'],
                },
            ],
        }
        const logic = modelBreakdownLogic({ filters })
        logic.mount()
        expect(mockApi.query).not.toHaveBeenCalled()
        mockApi.query.mockResolvedValueOnce({ results: [{ model: 'example-a', total_calls: 10 }], hasMore: true })

        await expectLogic(logic, () => logic.actions.setExpanded(true)).toFinishAllListeners()
        expect(mockApi.query).toHaveBeenLastCalledWith({
            ...filters,
            kind: NodeKind.MCPModelBreakdownQuery,
            includeAllModels: true,
            limit: MODEL_PAGE_SIZE,
            offset: 0,
        })
        expect(logic.values.modelPage?.results[0].model).toBe('example-a')

        mockApi.query.mockResolvedValueOnce({ results: [{ model: 'example-b', total_calls: 5 }], hasMore: false })
        await expectLogic(logic, () => logic.actions.loadModels(MODEL_PAGE_SIZE)).toFinishAllListeners()
        expect(mockApi.query).toHaveBeenLastCalledWith({
            ...filters,
            kind: NodeKind.MCPModelBreakdownQuery,
            includeAllModels: true,
            limit: MODEL_PAGE_SIZE,
            offset: MODEL_PAGE_SIZE,
        })
        expect(logic.values.modelPage).toMatchObject({
            offset: MODEL_PAGE_SIZE,
            hasMore: false,
            results: [{ model: 'example-b', total_calls: 5 }],
        })

        await expectLogic(logic, () => {
            logic.actions.setExpanded(false)
            logic.actions.setExpanded(true)
        }).toFinishAllListeners()
        expect(mockApi.query).toHaveBeenCalledTimes(2)

        const changedFiltersLogic = modelBreakdownLogic({ filters: { ...filters, dateRange: { date_from: '-7d' } } })
        changedFiltersLogic.mount()
        expect(changedFiltersLogic.values).toMatchObject({ expanded: false, modelPage: null })
    })

    it('exposes failed loads and retries the requested page', async () => {
        const logic = modelBreakdownLogic({ filters: {} })
        logic.mount()
        mockApi.query.mockRejectedValueOnce(new Error('Query failed'))
        await expectLogic(logic, () => logic.actions.loadModels(MODEL_PAGE_SIZE)).toFinishAllListeners()
        expect(logic.values).toMatchObject({
            loadFailed: true,
            requestedOffset: MODEL_PAGE_SIZE,
            modelPageLoading: false,
        })

        mockApi.query.mockResolvedValueOnce({ results: [], hasMore: false })
        await expectLogic(logic, () => logic.actions.loadModels(logic.values.requestedOffset)).toFinishAllListeners()
        expect(logic.values).toMatchObject({
            loadFailed: false,
            modelPage: { results: [], hasMore: false, offset: MODEL_PAGE_SIZE },
        })
    })
})
