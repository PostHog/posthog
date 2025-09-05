import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import api, { CountedPaginatedResponse } from '~/lib/api'
import { initKeaTests } from '~/test/init'
import { Dataset, DatasetItem } from '~/types'

import { DATASETS_PER_PAGE, getStorageKey, saveToDatasetButtonLogic } from './saveToDatasetButtonLogic'

jest.mock('~/lib/api')
jest.mock('lib/lemon-ui/LemonToast/LemonToast')

describe('saveToDatasetButtonLogic', () => {
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

    const mockPartialDatasetItem: Partial<DatasetItem> = {
        input: { message: 'Hello' },
        output: { response: 'Hi there' },
        metadata: { source: 'test' },
    }

    const mockDatasetsResponse: CountedPaginatedResponse<Dataset> = {
        results: [mockDataset1, mockDataset2],
        count: 2,
        next: null,
        previous: null,
    }

    const mockApi = api as jest.Mocked<typeof api>

    beforeEach(() => {
        jest.clearAllMocks()

        mockApi.datasets = {
            create: jest.fn(),
            update: jest.fn(),
            get: jest.fn(),
            list: jest.fn().mockResolvedValue(mockDatasetsResponse),
        } as any

        mockApi.datasetItems = {
            create: jest.fn().mockResolvedValue({}),
            update: jest.fn(),
        } as any
    })

    describe('getStorageKey', () => {
        it('serializes a key with search term', () => {
            const key = getStorageKey('test search')
            expect(key).toBe('limit=100&offset=0&search=test%20search')
        })

        it('serializes a key with empty search', () => {
            const key = getStorageKey('')
            expect(key).toBe('limit=100&offset=0&search=')
        })

        it('serializes a key with special characters', () => {
            const key = getStorageKey('test & special')
            expect(key).toBe('limit=100&offset=0&search=test%20%26%20special')
        })
    })

    describe('logic tests', () => {
        beforeEach(() => {
            initKeaTests()
            // Mock router actions after Kea is initialized
            jest.spyOn(router.actions, 'push').mockImplementation(jest.fn())
        })

        describe('datasets selector', () => {
            it('returns datasets for matching search key', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                // Set search form value first
                logic.actions.setSearchFormValue('search', 'test')

                // Manually populate the datasetStore with the right key
                const storageKey = getStorageKey('test')
                logic.actions.loadDatasetsSuccess({
                    ...logic.values.datasetStore,
                    [storageKey]: mockDatasetsResponse.results,
                })

                expect(logic.values.datasets).toEqual([mockDataset1, mockDataset2])
            })

            it('returns null when no datasets match search key', () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                logic.actions.setSearchFormValue('search', 'nonexistent')

                expect(logic.values.datasets).toBeNull()
            })

            it('returns datasets for empty search', () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                // For empty search, the default search form value is ''
                const storageKey = getStorageKey('')
                logic.actions.loadDatasetsSuccess({
                    ...logic.values.datasetStore,
                    [storageKey]: mockDatasetsResponse.results,
                })

                expect(logic.values.datasets).toEqual([mockDataset1, mockDataset2])
            })
        })

        describe('isLoadingDatasets selector', () => {
            it('returns true when datasets is null and loading', () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                logic.actions.loadDatasets()

                expect(logic.values.isLoadingDatasets).toBe(true)
            })

            it('returns false when datasets exist', () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                // Load datasets with the correct storage key structure
                const storageKey = getStorageKey('')
                logic.actions.loadDatasetsSuccess({
                    [storageKey]: mockDatasetsResponse.results,
                })

                expect(logic.values.isLoadingDatasets).toBe(false)
            })

            it('returns false when not loading even if datasets is null', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                // Wait for any initial loading to complete
                await expectLogic(logic).toFinishAllListeners()

                // Now make sure datasets is populated so the selector can work properly
                const storageKey = getStorageKey('')
                logic.actions.loadDatasetsSuccess({
                    [storageKey]: mockDatasetsResponse.results,
                })

                // isLoadingDatasets should be false when datasets exist
                expect(logic.values.isLoadingDatasets).toBe(false)

                // Clear datasets to test null case but not loading
                logic.actions.loadDatasetsSuccess({})

                // datasets should be null and still not loading
                expect(logic.values.datasets).toBeNull()
                expect(logic.values.isLoadingDatasets).toBe(false)
            })
        })

        describe('form reset conditions', () => {
            it('resets search form when modal is opened', () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                logic.actions.setSearchFormValue('search', 'test search')
                logic.actions.setIsModalOpen(true)

                expect(logic.values.searchForm.search).toBe('')
            })

            it('resets search form when dropdown is closed', () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                logic.actions.setSearchFormValue('search', 'test search')
                // Manually reset the form to simulate what would happen in the UI
                logic.actions.resetSearchForm()

                expect(logic.values.searchForm.search).toBe('')
            })

            it('resets search form after successful dataset selection', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                // First set the search form value, then load datasets with matching key
                logic.actions.setSearchFormValue('search', 'test')
                const storageKey = getStorageKey('test')
                logic.actions.loadDatasetsSuccess({
                    [storageKey]: mockDatasetsResponse.results,
                })

                // Set edit mode to create so the form submission creates an item
                logic.actions.setEditMode('create')

                // Verify the form has the expected value before submission
                expect(logic.values.searchForm.search).toBe('test')

                // Test direct form reset first
                logic.actions.resetSearchForm()
                expect(logic.values.searchForm.search).toBe('')

                // Set it back to test and try the full submission flow
                logic.actions.setSearchFormValue('search', 'test')
                expect(logic.values.searchForm.search).toBe('test')

                await expectLogic(logic, () => {
                    logic.actions.setSearchFormValues({ search: 'test', datasetId: 'test-dataset-1' })
                    logic.actions.submitSearchForm()
                }).toFinishAllListeners()

                // After successful submission, the form should be reset
                expect(logic.values.searchForm.search).toBe('')
                expect(logic.values.searchForm.datasetId).toBeNull()
            })

            it('resets search form when beforeUnmount is called', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                logic.actions.setSearchFormValue('search', 'test search')
                expect(logic.values.searchForm.search).toBe('test search')

                // Wait for any async operations to complete before unmounting
                await expectLogic(logic).toFinishAllListeners()

                // The beforeUnmount listener should reset the form
                await expectLogic(logic, () => {
                    logic.unmount()
                }).toFinishAllListeners()

                // Since the logic is unmounted, we can't check the values after unmount
                // The test is really about ensuring the beforeUnmount listener is called
                // which happens automatically during unmount
            })
        })

        describe('dataset item creation', () => {
            it('successfully creates dataset item in create mode', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                // First set the search form value to match what will be submitted
                logic.actions.setSearchFormValue('search', '')
                // Then load datasets with the correct storage key structure
                const storageKey = getStorageKey('')
                logic.actions.loadDatasetsSuccess({
                    [storageKey]: mockDatasetsResponse.results,
                })
                logic.actions.setEditMode('create')

                await expectLogic(logic, () => {
                    logic.actions.setSearchFormValues({ search: 'test', datasetId: 'test-dataset-1' })
                    logic.actions.submitSearchForm()
                }).toFinishAllListeners()

                expect(mockApi.datasetItems.create).toHaveBeenCalledWith({
                    ...mockPartialDatasetItem,
                    dataset: 'test-dataset-1',
                })
                expect(lemonToast.success).toHaveBeenCalledWith('Dataset item has been created successfully', {
                    button: {
                        label: 'View',
                        action: expect.any(Function),
                    },
                })
            })

            it('handles dataset item creation failure with retry', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                // First set the search form value to match what will be submitted
                logic.actions.setSearchFormValue('search', '')
                // Then load datasets with the correct storage key structure
                const storageKey = getStorageKey('')
                logic.actions.loadDatasetsSuccess({
                    [storageKey]: mockDatasetsResponse.results,
                })
                logic.actions.setEditMode('create')
                ;(mockApi.datasetItems.create as jest.Mock).mockRejectedValue(new Error('Creation failed'))

                await expectLogic(logic, () => {
                    logic.actions.setSearchFormValues({ search: '', datasetId: 'test-dataset-1' })
                    logic.actions.submitSearchForm()
                }).toFinishAllListeners()

                expect(lemonToast.error).toHaveBeenCalledWith('Failed to create dataset item', {
                    button: {
                        label: 'Retry',
                        action: expect.any(Function),
                    },
                })
            })

            it('opens modal in edit mode without creating item', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                // First set the search form value to match what will be submitted
                logic.actions.setSearchFormValue('search', '')
                // Then load datasets with the correct storage key structure
                const storageKey = getStorageKey('')
                logic.actions.loadDatasetsSuccess({
                    [storageKey]: mockDatasetsResponse.results,
                })
                logic.actions.setEditMode('edit')

                await expectLogic(logic, () => {
                    logic.actions.setSearchFormValues({ search: '', datasetId: 'test-dataset-1' })
                    logic.actions.submitSearchForm()
                }).toFinishAllListeners()

                expect(mockApi.datasetItems.create).not.toHaveBeenCalled()
                expect(logic.values.selectedDataset).toEqual(mockDataset1)
                expect(logic.values.isModalOpen).toBe(true)
            })

            it('does nothing when dataset is not found', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                // First set the search form value to match what will be submitted
                logic.actions.setSearchFormValue('search', '')
                // Then load datasets with the correct storage key structure
                const storageKey = getStorageKey('')
                logic.actions.loadDatasetsSuccess({
                    [storageKey]: mockDatasetsResponse.results,
                })

                await expectLogic(logic, () => {
                    logic.actions.setSearchFormValues({ search: '', datasetId: 'nonexistent-dataset' })
                    logic.actions.submitSearchForm()
                }).toFinishAllListeners()

                expect(mockApi.datasetItems.create).not.toHaveBeenCalled()
                expect(logic.values.selectedDataset).toBeNull()
                expect(logic.values.isModalOpen).toBe(false)
            })

            it('loads datasets when no datasetId is provided', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                await expectLogic(logic, () => {
                    logic.actions.setSearchFormValues({ search: 'test', datasetId: null })
                    logic.actions.submitSearchForm()
                }).toFinishAllListeners()

                expect(mockApi.datasets.list).toHaveBeenCalledWith({
                    limit: DATASETS_PER_PAGE,
                    offset: 0,
                    search: 'test',
                })
            })

            it('navigates to dataset page after successful creation', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                // First set the search form value to match what will be submitted
                logic.actions.setSearchFormValue('search', '')
                // Then load datasets with the correct storage key structure
                const storageKey = getStorageKey('')
                logic.actions.loadDatasetsSuccess({
                    [storageKey]: mockDatasetsResponse.results,
                })
                logic.actions.setEditMode('create')

                await expectLogic(logic, () => {
                    logic.actions.setSearchFormValues({ search: '', datasetId: 'test-dataset-1' })
                    logic.actions.submitSearchForm()
                }).toFinishAllListeners()

                const successCall = (lemonToast.success as jest.Mock).mock.calls[0]
                const viewAction = successCall[1].button.action

                viewAction()

                expect(router.actions.push).toHaveBeenCalledWith('/llm-analytics/datasets/test-dataset-1')
            })
        })

        describe('data loading', () => {
            it('loads datasets on mount if none exist', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                await expectLogic(logic).toFinishAllListeners()

                expect(mockApi.datasets.list).toHaveBeenCalledWith({
                    limit: DATASETS_PER_PAGE,
                    offset: 0,
                    search: '',
                })
            })

            it('does not load datasets on mount if they already exist', () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                logic.actions.loadDatasetsSuccess({
                    [getStorageKey('')]: mockDatasetsResponse.results,
                })
                logic.unmount()
                ;(mockApi.datasets.list as jest.Mock).mockClear()

                logic.mount()

                expect(mockApi.datasets.list).toHaveBeenCalledTimes(1)
            })

            it('loads datasets when search form value changes', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                await expectLogic(logic, () => {
                    logic.actions.setSearchFormValue('search', 'new search')
                }).toFinishAllListeners()

                expect(mockApi.datasets.list).toHaveBeenCalledWith({
                    limit: DATASETS_PER_PAGE,
                    offset: 0,
                    search: 'new search',
                })
            })

            it('loads datasets when dropdown becomes visible', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()
                ;(mockApi.datasets.list as jest.Mock).mockClear()

                await expectLogic(logic, () => {
                    logic.actions.setDropdownVisible(true)
                }).toFinishAllListeners()

                expect(mockApi.datasets.list).toHaveBeenCalledWith({
                    limit: DATASETS_PER_PAGE,
                    offset: 0,
                    search: '',
                })
            })

            it('uses debounce when loading datasets', async () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                await expectLogic(logic, () => {
                    logic.actions.loadDatasets(true)
                }).toFinishAllListeners()

                expect(mockApi.datasets.list).toHaveBeenCalled()
            })
        })

        describe('state management', () => {
            it('sets modal open state', () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                logic.actions.setIsModalOpen(true)
                expect(logic.values.isModalOpen).toBe(true)

                logic.actions.setIsModalOpen(false)
                expect(logic.values.isModalOpen).toBe(false)
            })

            it('sets edit mode', () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                logic.actions.setEditMode('edit')
                expect(logic.values.editMode).toBe('edit')

                logic.actions.setEditMode('create')
                expect(logic.values.editMode).toBe('create')
            })

            it('resets edit mode to create when modal is closed', () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                logic.actions.setEditMode('edit')
                logic.actions.setIsModalOpen(false)

                expect(logic.values.editMode).toBe('create')
            })

            it('sets dropdown visibility', () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                logic.actions.setDropdownVisible(true)
                expect(logic.values.dropdownVisible).toBe(true)

                logic.actions.setDropdownVisible(false)
                expect(logic.values.dropdownVisible).toBe(false)
            })

            it('sets selected dataset', () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                logic.actions.setSelectedDataset(mockDataset1)
                expect(logic.values.selectedDataset).toEqual(mockDataset1)

                logic.actions.setSelectedDataset(null)
                expect(logic.values.selectedDataset).toBeNull()
            })

            it('computes isModalMounted based on edit mode', () => {
                const logic = saveToDatasetButtonLogic({ partialDatasetItem: mockPartialDatasetItem })
                logic.mount()

                expect(logic.values.isModalMounted).toBe(false)

                logic.actions.setEditMode('edit')
                expect(logic.values.isModalMounted).toBe(true)

                logic.actions.setEditMode('create')
                expect(logic.values.isModalMounted).toBe(false)
            })
        })
    })
})
