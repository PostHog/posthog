import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import api from '~/lib/api'
import { initKeaTests } from '~/test/init'
import { Dataset, DatasetItem } from '~/types'

import { DatasetFormValues, DatasetLogicProps, llmAnalyticsDatasetLogic } from './llmAnalyticsDatasetLogic'
import { llmAnalyticsDatasetsLogic } from './llmAnalyticsDatasetsLogic'
import { EMPTY_JSON } from './utils'

jest.mock('~/lib/api')
jest.mock('lib/lemon-ui/LemonToast/LemonToast')

describe('llmAnalyticsDatasetLogic', () => {
    const mockDataset: Dataset = {
        id: 'test-dataset-id',
        name: 'Test Dataset',
        description: 'Test description',
        metadata: { key: 'value' },
        team: 997,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        created_by: {
            id: 1,
            uuid: 'test-uuid',
            distinct_id: 'test-distinct-id',
            first_name: 'Test',
            email: 'test@example.com',
        },
        deleted: false,
    }

    const mockDatasetItem1: DatasetItem = {
        id: 'item-1',
        dataset: 'test-dataset-id',
        team: 997,
        input: { query: 'test input' },
        output: { response: 'test response 1' },
        metadata: { key: 'value' },
        ref_trace_id: null,
        ref_timestamp: null,
        ref_source_id: null,
        created_by: {
            id: 1,
            uuid: 'test-uuid',
            distinct_id: 'test-distinct-id',
            first_name: 'Test',
            email: 'test@example.com',
        },
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        deleted: false,
    }

    const mockDatasetItem2: DatasetItem = {
        id: 'item-2',
        dataset: 'test-dataset-id',
        team: 997,
        input: { query: 'test input 2' },
        output: { response: 'test response 2' },
        metadata: { key: 'value2' },
        ref_trace_id: null,
        ref_timestamp: null,
        ref_source_id: null,
        created_by: {
            id: 1,
            uuid: 'test-uuid',
            distinct_id: 'test-distinct-id',
            first_name: 'Test',
            email: 'test@example.com',
        },
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        deleted: false,
    }

    const mockApi = api as jest.Mocked<typeof api>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()

        mockApi.datasets = {
            create: jest.fn(),
            update: jest.fn(),
            get: jest.fn(),
            list: jest.fn(),
        } as any
    })

    describe('new dataset creation', () => {
        let logic: ReturnType<typeof llmAnalyticsDatasetLogic.build>
        const props: DatasetLogicProps = { datasetId: 'new' }

        beforeEach(() => {
            logic = llmAnalyticsDatasetLogic(props)
            logic.mount()
        })

        it('has correct defaults for new dataset', () => {
            expect(logic.values.isNewDataset).toBe(true)
            expect(logic.values.dataset).toEqual({
                name: '',
                description: '',
                metadata: EMPTY_JSON,
            })
            expect(logic.values.datasetForm).toEqual({
                name: '',
                description: '',
                metadata: EMPTY_JSON,
            })
        })

        it('can create a new dataset with non-empty metadata', async () => {
            const formValues: DatasetFormValues = {
                name: 'New Dataset',
                description: 'New description',
                metadata: '{"test": "value"}',
            }

            ;(mockApi.datasets.create as jest.Mock).mockResolvedValue(mockDataset)
            const routerReplaceSpy = jest.spyOn(router.actions, 'replace')

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(mockApi.datasets.create as jest.Mock).toHaveBeenCalledWith({
                name: 'New Dataset',
                description: 'New description',
                metadata: { test: 'value' },
            })
            expect(lemonToast.success).toHaveBeenCalledWith('Dataset created successfully')
            expect(routerReplaceSpy).toHaveBeenCalledWith(urls.llmAnalyticsDataset(mockDataset.id))
            expect(logic.values.dataset).toEqual(mockDataset)
            expect(logic.values.isEditingDataset).toBe(false)
        })

        it('sends null for empty object metadata when creating dataset', async () => {
            const formValues: DatasetFormValues = {
                name: 'New Dataset',
                description: 'New description',
                metadata: EMPTY_JSON,
            }

            ;(mockApi.datasets.create as jest.Mock).mockResolvedValue(mockDataset)

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(mockApi.datasets.create as jest.Mock).toHaveBeenCalledWith({
                name: 'New Dataset',
                description: 'New description',
                metadata: null,
            })
        })

        it('sends null for empty string metadata when creating dataset', async () => {
            const formValues: DatasetFormValues = {
                name: 'New Dataset',
                description: 'New description',
                metadata: '',
            }

            ;(mockApi.datasets.create as jest.Mock).mockResolvedValue(mockDataset)

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(mockApi.datasets.create as jest.Mock).toHaveBeenCalledWith({
                name: 'New Dataset',
                description: 'New description',
                metadata: null,
            })
        })

        it('sends dictionary for non-empty metadata when creating dataset', async () => {
            const formValues: DatasetFormValues = {
                name: 'New Dataset',
                description: 'New description',
                metadata: '{"nested": {"key": "value"}, "array": [1, 2, 3]}',
            }

            ;(mockApi.datasets.create as jest.Mock).mockResolvedValue(mockDataset)

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(mockApi.datasets.create as jest.Mock).toHaveBeenCalledWith({
                name: 'New Dataset',
                description: 'New description',
                metadata: { nested: { key: 'value' }, array: [1, 2, 3] },
            })
        })

        it('handles creation error', async () => {
            const formValues: DatasetFormValues = {
                name: 'New Dataset',
                description: 'New description',
                metadata: '{"test": "value"}',
            }

            const error = { detail: 'Custom error message' }
            ;(mockApi.datasets.create as jest.Mock).mockRejectedValue(error)

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Custom error message')
        })

        it('handles creation error without detail', async () => {
            const formValues: DatasetFormValues = {
                name: 'New Dataset',
                description: 'New description',
                metadata: '{"test": "value"}',
            }

            const error = new Error('Network error')
            ;(mockApi.datasets.create as jest.Mock).mockRejectedValue(error)

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Failed to save dataset')
        })
    })

    describe('existing dataset editing', () => {
        let logic: ReturnType<typeof llmAnalyticsDatasetLogic.build>
        const props: DatasetLogicProps = { datasetId: 'existing-dataset-id' }

        beforeEach(() => {
            logic = llmAnalyticsDatasetLogic(props)
            logic.mount()
        })

        it('has correct defaults for existing dataset', () => {
            expect(logic.values.isNewDataset).toBe(false)
        })

        it('can edit an existing dataset', async () => {
            const formValues: DatasetFormValues = {
                name: 'Updated Dataset',
                description: 'Updated description',
                metadata: '{"updated": "metadata"}',
            }

            const updatedDataset = { ...mockDataset, ...formValues }
            ;(mockApi.datasets.update as jest.Mock).mockResolvedValue(updatedDataset)

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(mockApi.datasets.update as jest.Mock).toHaveBeenCalledWith('existing-dataset-id', {
                name: 'Updated Dataset',
                description: 'Updated description',
                metadata: { updated: 'metadata' },
            })
            expect(lemonToast.success).toHaveBeenCalledWith('Dataset updated successfully')
            expect(logic.values.dataset).toEqual(updatedDataset)
            expect(logic.values.isEditingDataset).toBe(false)
        })

        it('sends null for empty object metadata when editing dataset', async () => {
            const formValues: DatasetFormValues = {
                name: 'Updated Dataset',
                description: 'Updated description',
                metadata: EMPTY_JSON,
            }

            ;(mockApi.datasets.update as jest.Mock).mockResolvedValue(mockDataset)

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(mockApi.datasets.update as jest.Mock).toHaveBeenCalledWith('existing-dataset-id', {
                name: 'Updated Dataset',
                description: 'Updated description',
                metadata: null,
            })
        })

        it('handles update error', async () => {
            const formValues: DatasetFormValues = {
                name: 'Updated Dataset',
                description: 'Updated description',
                metadata: '{"test": "value"}',
            }

            const error = { detail: 'Update failed' }
            ;(mockApi.datasets.update as jest.Mock).mockRejectedValue(error)

            await expectLogic(logic, () => {
                logic.actions.setDatasetFormValues(formValues)
                logic.actions.submitDatasetForm()
            }).toFinishAllListeners()

            expect(lemonToast.error).toHaveBeenCalledWith('Update failed')
        })
    })

    describe('dataset loading and defaults', () => {
        let logic: ReturnType<typeof llmAnalyticsDatasetLogic.build>
        const props: DatasetLogicProps = { datasetId: 'existing-dataset-id' }

        beforeEach(() => {
            logic = llmAnalyticsDatasetLogic(props)
        })

        it('loads dataset on mount', async () => {
            ;(mockApi.datasets.get as jest.Mock).mockResolvedValue(mockDataset)
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(mockApi.datasets.get as jest.Mock).toHaveBeenCalledWith('existing-dataset-id')
        })

        it('sets form defaults when dataset is loaded', async () => {
            const datasetWithComplexMetadata: Dataset = {
                ...mockDataset,
                metadata: { complex: { nested: 'data' }, array: [1, 2, 3] },
            }

            ;(mockApi.datasets.get as jest.Mock).mockResolvedValue(datasetWithComplexMetadata)
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.loadDatasetSuccess(datasetWithComplexMetadata)
            }).toFinishAllListeners()

            expect(logic.values.datasetForm).toEqual({
                name: 'Test Dataset',
                description: 'Test description',
                metadata: '{\n  "complex": {\n    "nested": "data"\n  },\n  "array": [\n    1,\n    2,\n    3\n  ]\n}',
            })
        })

        it('uses existing dataset from datasets logic if available', () => {
            const datasetsLogic = llmAnalyticsDatasetsLogic()
            datasetsLogic.mount()

            // Mock the findMounted method to return the datasets logic
            const findMountedSpy = jest.spyOn(llmAnalyticsDatasetsLogic, 'findMounted')
            findMountedSpy.mockReturnValue({
                values: {
                    datasets: {
                        results: [mockDataset],
                    },
                },
            } as any)

            logic = llmAnalyticsDatasetLogic({ datasetId: mockDataset.id })
            logic.mount()

            expect(logic.values.dataset).toEqual(mockDataset)
            expect(logic.values.datasetForm).toEqual({
                name: 'Test Dataset',
                description: 'Test description',
                metadata: '{\n  "key": "value"\n}',
            })

            findMountedSpy.mockRestore()
        })

        it('handles null metadata correctly in form defaults', () => {
            const datasetWithNullMetadata = { ...mockDataset, metadata: null }

            const findMountedSpy = jest.spyOn(llmAnalyticsDatasetsLogic, 'findMounted')
            findMountedSpy.mockReturnValue({
                values: {
                    datasets: {
                        results: [datasetWithNullMetadata],
                    },
                },
            } as any)

            logic = llmAnalyticsDatasetLogic({ datasetId: datasetWithNullMetadata.id })
            logic.mount()

            expect(logic.values.datasetForm.metadata).toBe(EMPTY_JSON)

            findMountedSpy.mockRestore()
        })

        it('handles empty object metadata correctly in form defaults', () => {
            const datasetWithEmptyMetadata = { ...mockDataset, metadata: {} }

            const findMountedSpy = jest.spyOn(llmAnalyticsDatasetsLogic, 'findMounted')
            findMountedSpy.mockReturnValue({
                values: {
                    datasets: {
                        results: [datasetWithEmptyMetadata],
                    },
                },
            } as any)

            logic = llmAnalyticsDatasetLogic({ datasetId: datasetWithEmptyMetadata.id })
            logic.mount()

            expect(logic.values.datasetForm.metadata).toBe(EMPTY_JSON)

            findMountedSpy.mockRestore()
        })
    })

    describe('filter functionality', () => {
        let logic: ReturnType<typeof llmAnalyticsDatasetLogic.build>
        const props: DatasetLogicProps = { datasetId: 'existing-dataset-id' }

        beforeEach(() => {
            ;(mockApi.datasets.get as jest.Mock).mockResolvedValue(mockDataset)
            ;(mockApi.datasetItems.list as jest.Mock).mockResolvedValue({
                results: [],
                count: 0,
                offset: 0,
            })
            logic = llmAnalyticsDatasetLogic(props)
            logic.mount()
        })

        describe('filter processing and defaults', () => {
            it('applies default filters when no filters set', () => {
                expect(logic.values.filters).toEqual({
                    page: 1,
                    limit: 50,
                })
            })

            it('cleans and validates filter parameters', () => {
                logic.actions.setFilters({ page: '3' as any, limit: '25' as any })
                expect(logic.values.filters).toEqual({
                    page: 3,
                    limit: 25,
                })
            })

            it('handles invalid page parameter by setting default', () => {
                logic.actions.setFilters({ page: 'invalid' as any, limit: 25 })
                expect(logic.values.filters).toEqual({
                    page: 1,
                    limit: 25,
                })
            })

            it('handles invalid limit parameter by setting default', () => {
                logic.actions.setFilters({ page: 2, limit: 'invalid' as any })
                expect(logic.values.filters).toEqual({
                    page: 2,
                    limit: 50,
                })
            })

            it('resets page when other filters change', () => {
                logic.actions.setFilters({ page: 3, limit: 25 })
                expect(logic.values.filters.page).toBe(3)

                // Change limit, should reset page to 1
                logic.actions.setFilters({ limit: 100 })
                expect(logic.values.filters.page).toBe(1)
                expect(logic.values.filters.limit).toBe(100)
            })

            it('preserves page when explicitly changing page', () => {
                logic.actions.setFilters({ page: 2, limit: 25 })
                expect(logic.values.filters.page).toBe(2)

                // Explicitly change page, should not reset
                logic.actions.setFilters({ page: 5 })
                expect(logic.values.filters.page).toBe(5)
            })
        })

        describe('filter-triggered API calls', () => {
            it('loads dataset items when filters change', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({ page: 2, limit: 25 })
                }).toFinishAllListeners()

                expect(mockApi.datasetItems.list).toHaveBeenCalledWith({
                    dataset: 'existing-dataset-id',
                    offset: 50, // (page 2 - 1) * 50 (DATASET_ITEMS_PER_PAGE)
                    limit: 50, // DATASET_ITEMS_PER_PAGE constant
                })
            })

            it('calculates correct offset for pagination', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setFilters({ page: 3, limit: 25 })
                }).toFinishAllListeners()

                expect(mockApi.datasetItems.list).toHaveBeenCalledWith({
                    dataset: 'existing-dataset-id',
                    offset: 100, // (page 3 - 1) * 50 (DATASET_ITEMS_PER_PAGE)
                    limit: 50,
                })
            })

            it('does not trigger API call when filters do not change', async () => {
                const initialCallCount = (mockApi.datasetItems.list as jest.Mock).mock.calls.length

                await expectLogic(logic, () => {
                    logic.actions.setFilters({ page: 1, limit: 50 }) // Same as defaults
                }).toFinishAllListeners()

                expect(mockApi.datasetItems.list).toHaveBeenCalledTimes(initialCallCount) // Should not increase
            })
        })

        describe('dataset item modal and URL state', () => {
            it('opens modal when dataset item is selected from data', () => {
                const mockDatasetItems = {
                    results: [mockDatasetItem1, mockDatasetItem2],
                    count: 2,
                    offset: 0,
                }

                logic.actions.loadDatasetItemsSuccess(mockDatasetItems)
                logic.actions.setSelectedDatasetItem(mockDatasetItem1)
                logic.actions.triggerDatasetItemModal(true)

                expect(logic.values.selectedDatasetItem).toEqual(mockDatasetItem1)
                expect(logic.values.isDatasetItemModalOpen).toBe(true)
            })

            it('closes modal and clears selected item', async () => {
                const mockDatasetItems = {
                    results: [mockDatasetItem1],
                    count: 1,
                    offset: 0,
                }

                logic.actions.loadDatasetItemsSuccess(mockDatasetItems)
                logic.actions.setSelectedDatasetItem(mockDatasetItem1)
                logic.actions.triggerDatasetItemModal(true)

                await expectLogic(logic, () => {
                    logic.actions.closeModalAndRefetchDatasetItems(false)
                }).toFinishAllListeners()

                expect(logic.values.selectedDatasetItem).toBe(null)
                expect(logic.values.isDatasetItemModalOpen).toBe(false)
            })

            it('refetches dataset items when requested on modal close', async () => {
                const initialCallCount = (mockApi.datasetItems.list as jest.Mock).mock.calls.length

                await expectLogic(logic, () => {
                    logic.actions.closeModalAndRefetchDatasetItems(true)
                }).toFinishAllListeners()

                expect(mockApi.datasetItems.list).toHaveBeenCalledTimes(initialCallCount + 1)
            })
        })

        describe('URL integration with router', () => {
            beforeEach(() => {
                const mockDatasetItems = {
                    results: [mockDatasetItem1, mockDatasetItem2],
                    count: 2,
                    offset: 0,
                }
                logic.actions.loadDatasetItemsSuccess(mockDatasetItems)
            })

            it('handles URL with item parameter via urlToAction', async () => {
                // Test that urlToAction responds to URL changes with item parameter
                const datasetUrl = urls.llmAnalyticsDataset('existing-dataset-id')

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { item: 'item-1', page: '1' })
                }).toFinishAllListeners()

                // Verify modal opens with correct item selected
                expect(logic.values.selectedDatasetItem).toEqual(mockDatasetItem1)
                expect(logic.values.isDatasetItemModalOpen).toBe(true)
            })

            it('ignores URL item parameter when item not found', async () => {
                const datasetUrl = urls.llmAnalyticsDataset('existing-dataset-id')

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { item: 'non-existent-item', page: '1' })
                }).toFinishAllListeners()

                // Verify modal stays closed when item not found
                expect(logic.values.selectedDatasetItem).toBe(null)
                expect(logic.values.isDatasetItemModalOpen).toBe(false)
            })

            it('sets filters from URL parameters via urlToAction', async () => {
                const datasetUrl = urls.llmAnalyticsDataset('existing-dataset-id')

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { page: '3', limit: '25' })
                }).toFinishAllListeners()

                // Verify filters are set from URL
                expect(logic.values.filters).toEqual({
                    page: 3,
                    limit: 25,
                })
            })

            it('sets active tab from URL parameters via urlToAction', async () => {
                const datasetUrl = urls.llmAnalyticsDataset('existing-dataset-id')

                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { tab: 'metadata', page: '1' })
                }).toFinishAllListeners()

                // Verify tab is set from URL
                expect(logic.values.activeTab).toBe('metadata')
            })

            it('closes modal and clears state when closeModalAndRefetchDatasetItems is called', async () => {
                // Set up initial state with modal open
                logic.actions.setSelectedDatasetItem(mockDatasetItem1)
                logic.actions.triggerDatasetItemModal(true)

                // Close modal
                await expectLogic(logic, () => {
                    logic.actions.closeModalAndRefetchDatasetItems(false)
                }).toFinishAllListeners()

                // Verify modal state is cleared
                expect(logic.values.selectedDatasetItem).toBe(null)
                expect(logic.values.isDatasetItemModalOpen).toBe(false)
            })

            it('handles complete workflow: URL -> modal -> close', async () => {
                const datasetUrl = urls.llmAnalyticsDataset('existing-dataset-id')

                // Step 1: Navigate to URL with item parameter
                await expectLogic(logic, () => {
                    router.actions.push(datasetUrl, { item: 'item-1', page: '1' })
                }).toFinishAllListeners()

                // Verify modal opened via urlToAction
                expect(logic.values.selectedDatasetItem).toEqual(mockDatasetItem1)
                expect(logic.values.isDatasetItemModalOpen).toBe(true)

                // Step 2: Close modal
                await expectLogic(logic, () => {
                    logic.actions.closeModalAndRefetchDatasetItems(false)
                }).toFinishAllListeners()

                // Verify modal state cleared
                expect(logic.values.selectedDatasetItem).toBe(null)
                expect(logic.values.isDatasetItemModalOpen).toBe(false)
            })
        })
    })

    describe('form validation', () => {
        let logic: ReturnType<typeof llmAnalyticsDatasetLogic.build>

        beforeEach(() => {
            logic = llmAnalyticsDatasetLogic({ datasetId: 'new' })
            logic.mount()
        })

        it('validates required name field', async () => {
            const formValues = { name: '', description: 'test', metadata: '{}' }
            logic.actions.setDatasetFormValues(formValues)

            try {
                await expectLogic(logic, () => {
                    logic.actions.submitDatasetForm()
                }).toFinishAllListeners()
            } catch {
                // Expected to fail validation
            }

            const errors = logic.values.datasetFormErrors
            expect(errors.name).toBe('Dataset name is required')
        })

        it('validates name with only whitespace', async () => {
            const formValues = { name: '   ', description: 'test', metadata: '{}' }
            logic.actions.setDatasetFormValues(formValues)

            try {
                await expectLogic(logic, () => {
                    logic.actions.submitDatasetForm()
                }).toFinishAllListeners()
            } catch {
                // Expected to fail validation
            }

            const errors = logic.values.datasetFormErrors
            expect(errors.name).toBe('Dataset name is required')
        })

        it('validates valid metadata JSON', async () => {
            const formValues = { name: 'test', description: 'test', metadata: '{"valid": "json"}' }
            logic.actions.setDatasetFormValues(formValues)
            logic.actions.touchDatasetFormField('metadata')

            await expectLogic(logic).toFinishAllListeners()

            const errors = logic.values.datasetFormErrors
            expect(errors.metadata).toBeUndefined()
        })

        it('validates invalid metadata JSON', async () => {
            const formValues = { name: 'test', description: 'test', metadata: '{"invalid": json}' }
            logic.actions.setDatasetFormValues(formValues)

            try {
                await expectLogic(logic, () => {
                    logic.actions.submitDatasetForm()
                }).toFinishAllListeners()
            } catch {
                // Expected to fail validation
            }

            const errors = logic.values.datasetFormErrors
            expect(errors.metadata).toBe('Dataset metadata must contain a valid JSON object or be empty')
        })

        it('allows empty metadata', async () => {
            const formValues = { name: 'test', description: 'test', metadata: '' }
            logic.actions.setDatasetFormValues(formValues)
            logic.actions.touchDatasetFormField('metadata')

            await expectLogic(logic).toFinishAllListeners()

            const errors = logic.values.datasetFormErrors
            expect(errors.metadata).toBeUndefined()
        })

        it('allows null metadata', async () => {
            const formValues = { name: 'test', description: 'test', metadata: null }
            logic.actions.setDatasetFormValues(formValues)
            logic.actions.touchDatasetFormField('metadata')

            await expectLogic(logic).toFinishAllListeners()

            const errors = logic.values.datasetFormErrors
            expect(errors.metadata).toBeUndefined()
        })
    })
})
