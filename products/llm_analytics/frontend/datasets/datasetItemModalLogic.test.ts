import { expectLogic } from 'kea-test-utils'

import api from '~/lib/api'
import { initKeaTests } from '~/test/init'
import { DatasetItem } from '~/types'

import { datasetItemModalLogic } from './datasetItemModalLogic'
import { EMPTY_JSON } from './utils'

jest.mock('~/lib/api')

describe('datasetItemModalLogic', () => {
    const mockDatasetItem: DatasetItem = {
        id: 'test-item-1',
        dataset: 'test-dataset-1',
        team: 997,
        input: { message: 'Hello' },
        output: { response: 'Hi there' },
        metadata: { source: 'test' },
        ref_trace_id: null,
        ref_timestamp: null,
        ref_source_id: null,
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

    const mockApi = api as jest.Mocked<typeof api>
    const mockCloseModal = jest.fn()

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()

        mockApi.datasetItems = {
            create: jest.fn().mockResolvedValue(mockDatasetItem),
            update: jest.fn().mockResolvedValue(mockDatasetItem),
        } as any
    })

    it('save resets shouldCloseModal to true after creating item', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: null,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()

        // Set shouldCloseModal to false initially
        logic.actions.setShouldCloseModal(false)
        expect(logic.values.shouldCloseModal).toBe(false)

        // Submit form
        await expectLogic(logic, () => {
            logic.actions.submitDatasetItemForm()
        }).toFinishAllListeners()

        expect(logic.values.shouldCloseModal).toBe(true)
    })

    it('save closes modal when shouldCloseModal is true', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: null,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()

        // shouldCloseModal is true by default
        expect(logic.values.shouldCloseModal).toBe(true)

        // Submit form
        await expectLogic(logic, () => {
            logic.actions.submitDatasetItemForm()
        }).toFinishAllListeners()

        expect(mockCloseModal).toHaveBeenCalledWith(true)
    })

    it('save does not close modal when shouldCloseModal is false', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: null,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()

        // Set shouldCloseModal to false
        logic.actions.setShouldCloseModal(false)

        // Submit form
        await expectLogic(logic, () => {
            logic.actions.submitDatasetItemForm()
        }).toFinishAllListeners()

        expect(mockCloseModal).not.toHaveBeenCalled()
        expect(logic.values.refetchDatasetItems).toBe(true)
    })

    it('edit closes the modal', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: mockDatasetItem,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()

        // Mock successful update
        const updatedItem = { ...mockDatasetItem, output: { response: 'Updated response' } }
        ;(mockApi.datasetItems.update as jest.Mock).mockResolvedValue(updatedItem)

        // Submit form
        await expectLogic(logic, () => {
            logic.actions.submitDatasetItemForm()
        }).toFinishAllListeners()

        expect(mockCloseModal).toHaveBeenCalledWith(true)
    })

    it('sets correct default form values for new dataset item', () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: null,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()

        expect(logic.values.datasetItemForm).toEqual({
            input: EMPTY_JSON,
            output: EMPTY_JSON,
            metadata: EMPTY_JSON,
        })
    })

    it('sets correct default form values for existing dataset item', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: mockDatasetItem,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.datasetItemForm.input).toContain('"message": "Hello"')
        expect(logic.values.datasetItemForm.output).toContain('"response": "Hi there"')
        expect(logic.values.datasetItemForm.metadata).toContain('"source": "test"')
    })

    it('resets form values to default when saving without closing modal', async () => {
        const logic = datasetItemModalLogic({
            datasetId: 'test-dataset-1',
            partialDatasetItem: null,
            closeModal: mockCloseModal,
            isModalOpen: true,
        })
        logic.mount()

        // Set shouldCloseModal to false to trigger "save and add another" behavior
        logic.actions.setShouldCloseModal(false)

        // Set some custom form values
        logic.actions.setDatasetItemFormValues({
            input: '{"custom": "input"}',
            output: '{"custom": "output"}',
            metadata: '{"custom": "metadata"}',
        })

        // Verify form has custom values
        expect(logic.values.datasetItemForm).toEqual({
            input: '{"custom": "input"}',
            output: '{"custom": "output"}',
            metadata: '{"custom": "metadata"}',
        })

        // Submit form
        await expectLogic(logic, () => {
            logic.actions.submitDatasetItemForm()
        }).toFinishAllListeners()

        expect(logic.values.datasetItemForm).toEqual({
            input: EMPTY_JSON,
            output: EMPTY_JSON,
            metadata: EMPTY_JSON,
        })
    })
})
