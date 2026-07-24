import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { InfiniteListLogicProps, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { PropertyFilterType } from '~/types'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowTaxonomicFilters } from './HogFlowTaxonomicFilters'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
}))

jest.mock('lib/components/TaxonomicFilter/infiniteListLogic', () => ({
    infiniteListLogic: jest.fn(),
}))

jest.mock('../../workflowLogic', () => ({
    workflowLogic: { __mock: 'workflowLogic' },
}))

const mockedUseValues = useValues as jest.Mock
const mockedInfiniteListLogic = infiniteListLogic as unknown as jest.Mock

const INFINITE_LIST_LOGIC_PROPS: InfiniteListLogicProps = {
    taxonomicFilterLogicKey: 'test-key',
    listGroupType: TaxonomicFilterGroupType.WorkflowVariables,
    taxonomicGroupTypes: [TaxonomicFilterGroupType.WorkflowVariables],
}

const VARIABLE_FOO = {
    type: 'string' as const,
    key: 'foo_var',
    label: 'Foo variable',
}
const VARIABLE_BAR = {
    type: 'number' as const,
    key: 'bar_var',
    label: 'Bar variable',
}
const VARIABLE_BAZ = {
    type: 'string' as const,
    key: 'baz_var',
    label: 'Hello world',
}

function setupMocks({
    variables,
    trimmedSearchQuery = '',
}: {
    variables: Array<Record<string, unknown>> | undefined
    trimmedSearchQuery?: string
}): void {
    const infiniteListLogicRef = { __mock: 'infiniteListLogicInstance' }
    mockedInfiniteListLogic.mockReturnValue(infiniteListLogicRef)

    mockedUseValues.mockImplementation((logic: unknown) => {
        if (logic === workflowLogic) {
            return { workflow: variables === undefined ? null : { variables } }
        }
        if (logic === infiniteListLogicRef) {
            return { trimmedSearchQuery }
        }
        return {}
    })
}

function renderComponent(): { onChange: jest.Mock } {
    const onChange = jest.fn()
    render(<HogFlowTaxonomicFilters onChange={onChange} infiniteListLogicProps={INFINITE_LIST_LOGIC_PROPS} />)
    return { onChange }
}

describe('HogFlowTaxonomicFilters', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        { description: 'workflow has no variables', variables: [] as Array<Record<string, unknown>> },
        { description: 'workflow is null', variables: undefined },
    ])('renders the no-variables empty state when $description', ({ variables }) => {
        setupMocks({ variables })
        renderComponent()
        expect(screen.getByText('No workflow variables defined.')).toBeInTheDocument()
    })

    it.each([
        {
            description: 'renders all variables when the search query is empty',
            variables: [VARIABLE_FOO, VARIABLE_BAR, VARIABLE_BAZ],
            trimmedSearchQuery: '',
            visible: ['foo_var', 'bar_var', 'baz_var'],
            hidden: ['No workflow variables match your search.'],
        },
        {
            description: 'filters by key (case-insensitive)',
            variables: [VARIABLE_FOO, VARIABLE_BAR],
            trimmedSearchQuery: 'FOO',
            visible: ['foo_var'],
            hidden: ['bar_var'],
        },
        {
            description: 'filters by label',
            variables: [VARIABLE_FOO, VARIABLE_BAR, VARIABLE_BAZ],
            trimmedSearchQuery: 'hello',
            visible: ['baz_var'],
            hidden: ['foo_var', 'bar_var'],
        },
        {
            description: 'renders a friendly empty state when no variables match the search',
            variables: [VARIABLE_FOO, VARIABLE_BAR],
            trimmedSearchQuery: 'nope',
            visible: ['No workflow variables match your search.'],
            hidden: ['foo_var'],
        },
    ])('$description', ({ variables, trimmedSearchQuery, visible, hidden }) => {
        setupMocks({ variables, trimmedSearchQuery })
        renderComponent()
        visible.forEach((text) => expect(screen.getByText(text)).toBeInTheDocument())
        hidden.forEach((text) => expect(screen.queryByText(text)).not.toBeInTheDocument())
    })

    it('calls onChange with the workflow variable filter group when a variable is clicked', () => {
        setupMocks({ variables: [VARIABLE_FOO] })
        const { onChange } = renderComponent()

        fireEvent.click(screen.getByText('foo_var'))

        expect(onChange).toHaveBeenCalledTimes(1)
        expect(onChange).toHaveBeenCalledWith('foo_var', {
            key: 'foo_var',
            name: 'foo_var',
            propertyFilterType: PropertyFilterType.WorkflowVariable,
            taxonomicFilterGroup: TaxonomicFilterGroupType.WorkflowVariables,
        })
    })
})
