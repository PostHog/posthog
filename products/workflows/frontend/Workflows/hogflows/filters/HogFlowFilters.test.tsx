import '@testing-library/jest-dom'

import { renderHook } from '@testing-library/react'
import { useValues } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { workflowLogic } from '../../workflowLogic'
import { useWorkflowVariableTaxonomicOptions } from './HogFlowFilters'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
}))

jest.mock('../../workflowLogic', () => ({
    workflowLogic: { __mock: 'workflowLogic' },
}))

const mockedUseValues = useValues as jest.Mock

function setupWorkflowLogicMock(workflow: unknown): void {
    mockedUseValues.mockImplementation((logic: unknown) => {
        if (logic === workflowLogic) {
            return { workflow }
        }
        return {}
    })
}

describe('useWorkflowVariableTaxonomicOptions', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('returns each workflow variable as a SimpleOption keyed by `name`', () => {
        setupWorkflowLogicMock({
            variables: [
                { type: 'string', key: 'order_id', label: 'Order ID' },
                { type: 'number', key: 'amount', label: 'Amount' },
            ],
        })

        const { result } = renderHook(() => useWorkflowVariableTaxonomicOptions())

        expect(result.current).toEqual({
            [TaxonomicFilterGroupType.WorkflowVariables]: [{ name: 'order_id' }, { name: 'amount' }],
        })
    })

    it.each([
        { description: 'workflow has no variables', workflow: { variables: [] } },
        { description: 'workflow itself is null', workflow: null },
        { description: 'variables is undefined', workflow: { variables: undefined } },
    ])('returns an empty list when $description', ({ workflow }) => {
        setupWorkflowLogicMock(workflow)

        const { result } = renderHook(() => useWorkflowVariableTaxonomicOptions())

        expect(result.current).toEqual({
            [TaxonomicFilterGroupType.WorkflowVariables]: [],
        })
    })
})
