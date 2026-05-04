import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { recentTaxonomicFiltersLogic } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { mockActionDefinition, mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { HogFlowPropertyFilters } from './HogFlowFilters'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

const ORDER_ID_VARIABLE = { type: 'string' as const, key: 'order_id', label: 'Order ID', default_value: '' }
const CART_TOTAL_VARIABLE = { type: 'number' as const, key: 'cart_total', label: 'Cart total', default_value: 0 }
const SHIPPING_COUNTRY_VARIABLE = {
    type: 'string' as const,
    key: 'shipping_country',
    label: 'Shipping country',
    default_value: '',
}

describe('HogFlowPropertyFilters search', () => {
    let unmountWorkflowLogic: (() => void) | null = null
    let mountedWorkflowLogic: ReturnType<typeof workflowLogic.build> | null = null

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/actions': { results: [mockActionDefinition] },
                '/api/environments/:team/persons/properties': [],
                '/api/environments/:team/events/values': { results: [], refreshing: false },
                '/api/environments/:team_id/quick_filters/': { results: [] },
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
        propertyDefinitionsModel.mount()
        recentTaxonomicFiltersLogic.mount()
        mountedWorkflowLogic = workflowLogic({ id: 'new', tabId: 'default' })
        unmountWorkflowLogic = mountedWorkflowLogic.mount()
    })

    afterEach(() => {
        unmountWorkflowLogic?.()
        unmountWorkflowLogic = null
        mountedWorkflowLogic = null
        cleanup()
    })

    function setWorkflowVariables(variables: Array<Record<string, unknown>>): void {
        mountedWorkflowLogic!.actions.setWorkflowInfo({ variables: variables as any })
    }

    function renderFilters(): { setFilters: jest.Mock } {
        const setFilters = jest.fn()
        const filters = { properties: [] } as HogFlowAction['filters']
        render(
            <Provider>
                <HogFlowPropertyFilters filtersKey="search-test" filters={filters} setFilters={setFilters} />
            </Provider>
        )
        return { setFilters }
    }

    async function openTaxonomicFilter(): Promise<void> {
        fireEvent.click(screen.getByTestId('new-prop-filter-HogFlowPropertyFilters.search-test'))
        await waitFor(() => {
            expect(screen.getByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()
        })
    }

    function search(query: string): void {
        fireEvent.change(screen.getByTestId('taxonomic-filter-searchfield'), { target: { value: query } })
    }

    it('shows workflow variables in the dedicated tab', async () => {
        setWorkflowVariables([ORDER_ID_VARIABLE, CART_TOTAL_VARIABLE])
        renderFilters()

        await openTaxonomicFilter()
        fireEvent.click(screen.getByTestId('taxonomic-tab-workflow_variables'))

        await waitFor(() => {
            expect(screen.getAllByRole('button', { name: 'order_id' }).length).toBeGreaterThan(0)
        })
        expect(screen.getAllByRole('button', { name: 'cart_total' }).length).toBeGreaterThan(0)
    })

    it('filters workflow variables by search query in the dedicated tab', async () => {
        setWorkflowVariables([ORDER_ID_VARIABLE, CART_TOTAL_VARIABLE, SHIPPING_COUNTRY_VARIABLE])
        renderFilters()

        await openTaxonomicFilter()
        fireEvent.click(screen.getByTestId('taxonomic-tab-workflow_variables'))
        search('cart')

        await waitFor(() => {
            expect(screen.getAllByRole('button', { name: 'cart_total' }).length).toBeGreaterThan(0)
        })
        expect(screen.queryByRole('button', { name: 'order_id' })).not.toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'shipping_country' })).not.toBeInTheDocument()
    })

    it('surfaces workflow variables in the All/Suggestions tab when searching', async () => {
        setWorkflowVariables([ORDER_ID_VARIABLE, CART_TOTAL_VARIABLE])
        renderFilters()

        await openTaxonomicFilter()
        search('order')

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-workflow_variables-0')).toBeInTheDocument()
        })
        expect(screen.getByTestId('prop-filter-workflow_variables-0')).toHaveTextContent('order_id')
    })

    it('shows an empty state in the workflow variables tab when no variables match the search', async () => {
        setWorkflowVariables([ORDER_ID_VARIABLE])
        renderFilters()

        await openTaxonomicFilter()
        fireEvent.click(screen.getByTestId('taxonomic-tab-workflow_variables'))
        search('zzznonexistent')

        await waitFor(() => {
            expect(screen.getAllByText('No workflow variables match your search.').length).toBeGreaterThan(0)
        })
    })
})
