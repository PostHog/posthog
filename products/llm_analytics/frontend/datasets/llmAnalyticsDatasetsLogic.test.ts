import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import api from '~/lib/api'
import { initKeaTests } from '~/test/init'
import { Dataset } from '~/types'

import { DATASETS_PER_PAGE, llmAnalyticsDatasetsLogic } from './llmAnalyticsDatasetsLogic'

jest.mock('~/lib/api')
jest.mock('lib/lemon-ui/LemonToast/LemonToast')

describe('llmAnalyticsDatasetsLogic', () => {
    const mockDataset1: Dataset = {
        id: 'test-dataset-1',
        name: 'Test Dataset 1',
        description: 'First test dataset',
        metadata: { key1: 'value1' },
        team: 997,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        created_by: {
            id: 1,
            uuid: 'test-uuid-1',
            distinct_id: 'test-distinct-id-1',
            first_name: 'Test',
            email: 'test1@example.com',
        },
        deleted: false,
    }

    const mockDataset2: Dataset = {
        id: 'test-dataset-2',
        name: 'Test Dataset 2',
        description: 'Second test dataset',
        metadata: { key2: 'value2' },
        team: 997,
        created_at: '2024-01-02T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
        created_by: {
            id: 2,
            uuid: 'test-uuid-2',
            distinct_id: 'test-distinct-id-2',
            first_name: 'Test2',
            email: 'test2@example.com',
        },
        deleted: false,
    }

    const mockDatasetsResponse = {
        results: [mockDataset1, mockDataset2],
        count: 2,
        offset: 0,
    }

    const mockApi = api as jest.Mocked<typeof api>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()

        mockApi.datasets = {
            create: jest.fn(),
            update: jest.fn(),
            get: jest.fn(),
            list: jest.fn().mockResolvedValue(mockDatasetsResponse),
        } as any
    })

    describe('filters functionality', () => {
        it('sets and processes filters correctly', () => {
            const logic = llmAnalyticsDatasetsLogic()
            logic.mount()

            // Test setting filters with merge=false
            logic.actions.setFilters(
                {
                    page: 2,
                    search: 'test search',
                    order_by: 'name',
                },
                false
            )

            expect(logic.values.filters).toEqual({
                page: 2,
                search: 'test search',
                order_by: 'name',
            })
        })

        it('handles invalid page parameter', () => {
            const logic = llmAnalyticsDatasetsLogic()
            logic.mount()

            logic.actions.setFilters(
                {
                    page: 'invalid' as any,
                    search: '',
                    order_by: '-created_at',
                },
                false
            )

            expect(logic.values.filters.page).toBe(1) // Defaults to 1 for invalid input
        })

        it('applies default values for missing parameters', () => {
            const logic = llmAnalyticsDatasetsLogic()
            logic.mount()

            logic.actions.setFilters({}, false)

            expect(logic.values.filters).toEqual({
                page: 1,
                search: '',
                order_by: '-created_at',
            })
        })

        it('resets page when non-page filter changes', () => {
            const logic = llmAnalyticsDatasetsLogic()
            logic.mount()

            // Set initial page
            logic.actions.setFilters({ page: 3 }, false)
            expect(logic.values.filters.page).toBe(3)

            // Change search filter - should reset page to 1
            logic.actions.setFilters({ search: 'test' })
            expect(logic.values.filters.page).toBe(1)
            expect(logic.values.filters.search).toBe('test')
        })

        it('does not reset page when page filter changes', () => {
            const logic = llmAnalyticsDatasetsLogic()
            logic.mount()

            // Set initial filters
            logic.actions.setFilters({ search: 'test', page: 1 }, false)

            // Change only page - should not reset
            logic.actions.setFilters({ page: 3 })
            expect(logic.values.filters.page).toBe(3)
            expect(logic.values.filters.search).toBe('test')
        })
    })

    describe('loading datasets when filters change', () => {
        it('loads datasets on mount', async () => {
            const logic = llmAnalyticsDatasetsLogic()
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(mockApi.datasets.list).toHaveBeenCalledWith({
                search: '',
                order_by: '-created_at',
                offset: 0,
                limit: DATASETS_PER_PAGE,
            })
        })

        it('creates correct query parameters for search filter', () => {
            const logic = llmAnalyticsDatasetsLogic()
            logic.mount()

            // Test with search filter
            logic.actions.setFilters({ search: 'new search' }, false)

            // Check that the selector computes correct parameters
            expect(logic.values.filters.search).toBe('new search')
            expect(logic.values.filters.page).toBe(1) // Reset to page 1
            expect(mockApi.datasets.list).toHaveBeenCalledWith({
                search: 'new search',
                order_by: '-created_at',
                offset: 0,
                limit: DATASETS_PER_PAGE,
            })
        })

        it('creates correct query parameters for page changes', () => {
            const logic = llmAnalyticsDatasetsLogic()
            logic.mount()

            logic.actions.setFilters({ page: 3 }, false)

            expect(logic.values.filters.page).toBe(3)
            expect(mockApi.datasets.list).toHaveBeenCalledWith({
                search: '',
                order_by: '-created_at',
                offset: DATASETS_PER_PAGE * 2,
                limit: DATASETS_PER_PAGE,
            })
        })

        it('creates correct query parameters for order_by changes', () => {
            const logic = llmAnalyticsDatasetsLogic()
            logic.mount()

            logic.actions.setFilters({ order_by: 'name' }, false)

            expect(mockApi.datasets.list).toHaveBeenCalledWith({
                search: '',
                order_by: 'name',
                offset: 0,
                limit: DATASETS_PER_PAGE,
            })
        })
    })

    describe('dataset deletion', () => {
        it('successfully deletes a dataset', async () => {
            const logic = llmAnalyticsDatasetsLogic()
            logic.mount()

            // Set up datasets in state first
            logic.actions.loadDatasetsSuccess(mockDatasetsResponse)
            ;(mockApi.datasets.update as jest.Mock).mockResolvedValue({ ...mockDataset1, deleted: true })

            await expectLogic(logic, () => {
                logic.actions.deleteDataset(mockDataset1.id)
            }).toFinishAllListeners()

            expect(mockApi.datasets.update).toHaveBeenCalledWith(mockDataset1.id, { deleted: true })
            expect(lemonToast.info).toHaveBeenCalledWith(`${mockDataset1.name} has been deleted.`)
        })

        it('handles deletion error', async () => {
            const logic = llmAnalyticsDatasetsLogic()
            logic.mount()
            ;(mockApi.datasets.update as jest.Mock).mockRejectedValue(new Error('Delete failed'))

            await expectLogic(logic, () => {
                logic.actions.deleteDataset(mockDataset1.id)
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Failed to delete dataset')
        })
    })

    describe('selectors', () => {
        let logic: ReturnType<typeof llmAnalyticsDatasetsLogic.build>

        beforeEach(() => {
            logic = llmAnalyticsDatasetsLogic()
            logic.mount()
        })

        it('computes sorting correctly for descending order', () => {
            logic.actions.setFilters({ order_by: '-name' }, false)

            expect(logic.values.sorting).toEqual({
                columnKey: 'name',
                order: -1,
            })
        })

        it('computes sorting correctly for ascending order', () => {
            logic.actions.setFilters({ order_by: 'created_at' }, false)

            expect(logic.values.sorting).toEqual({
                columnKey: 'created_at',
                order: 1,
            })
        })

        it('computes sorting default when no order_by is set', () => {
            // When order_by is empty string, cleanFilters will default it to '-created_at'
            logic.actions.setFilters({ order_by: '' }, false)

            expect(logic.values.sorting).toEqual({
                columnKey: 'created_at',
                order: -1,
            })
        })

        it('computes pagination correctly', () => {
            logic.actions.setFilters({ page: 2 }, false)
            logic.actions.loadDatasetsSuccess({ results: [], count: 100 })

            expect(logic.values.pagination).toEqual({
                controlled: true,
                pageSize: DATASETS_PER_PAGE,
                currentPage: 2,
                entryCount: 100,
            })
        })

        it('computes dataset count label correctly for multiple results', () => {
            logic.actions.setFilters({ page: 2 }, false)
            logic.actions.loadDatasetsSuccess({ results: [], count: 100 })

            expect(logic.values.datasetCountLabel).toBe('31-60 of 100 datasets')
        })

        it('computes dataset count label correctly for single result', () => {
            logic.actions.loadDatasetsSuccess({ results: [], count: 1 })

            expect(logic.values.datasetCountLabel).toBe('1-1 of 1 dataset')
        })

        it('computes dataset count label correctly for no results', () => {
            logic.actions.loadDatasetsSuccess({ results: [], count: 0 })

            expect(logic.values.datasetCountLabel).toBe('0 datasets')
        })

        it('computes dataset count label correctly for last page', () => {
            logic.actions.setFilters({ page: 4 }, false)
            logic.actions.loadDatasetsSuccess({ results: [], count: 95 })

            expect(logic.values.datasetCountLabel).toBe('91-95 of 95 datasets')
        })
    })

    it('validates filter changes', () => {
        const logic = llmAnalyticsDatasetsLogic()
        logic.mount()

        // Test that changing filters updates the state correctly
        logic.actions.setFilters({ search: 'test search' }, false)
        expect(logic.values.filters.search).toBe('test search')

        logic.actions.setFilters({ page: 2 }, false)
        expect(logic.values.filters.page).toBe(2)

        logic.actions.setFilters({ order_by: 'name' }, false)
        expect(logic.values.filters.order_by).toBe('name')
    })
})
