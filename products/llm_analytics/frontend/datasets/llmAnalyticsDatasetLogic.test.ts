import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import api from '~/lib/api'
import { initKeaTests } from '~/test/init'

import { DatasetFormValues, DatasetLogicProps, llmAnalyticsDatasetLogic } from './llmAnalyticsDatasetLogic'
import { llmAnalyticsDatasetsLogic } from './llmAnalyticsDatasetsLogic'
import { EMPTY_JSON } from './utils'

jest.mock('~/lib/api')
jest.mock('lib/lemon-ui/LemonToast/LemonToast')

describe('llmAnalyticsDatasetLogic', () => {
    const mockDataset = {
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
            const datasetWithComplexMetadata = {
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
