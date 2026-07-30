import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import {
    EventPropertyFilter,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { FilterGroup } from './FilterGroup'
import { issueFiltersLogic } from './issueFiltersLogic'

jest.mock('lib/components/PropertyFilters/components/PropertyFilterIcon', () => ({
    PropertyFilterIcon: (): JSX.Element => <span />,
}))

const LOGIC_KEY = 'test'

const firefoxFilter: EventPropertyFilter = {
    type: PropertyFilterType.Event,
    key: '$browser',
    operator: PropertyOperator.Exact,
    value: ['Firefox'],
}

const chromeFilter: EventPropertyFilter = {
    type: PropertyFilterType.Event,
    key: '$browser',
    operator: PropertyOperator.Exact,
    value: ['Chrome'],
}

describe('FilterGroup', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/quick_filters/': { results: [] },
                '/api/projects/:team_id/surveys/question_labels/': { labels: [] },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows and updates the operator for OR filter groups', async () => {
        const logic = issueFiltersLogic({ logicKey: LOGIC_KEY })
        logic.mount()
        logic.actions.setFilterGroup({
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.Or, values: [firefoxFilter, chromeFilter] }],
        })

        render(
            <Provider>
                <BindLogic logic={issueFiltersLogic} props={{ logicKey: LOGIC_KEY }}>
                    <FilterGroup />
                </BindLogic>
            </Provider>
        )

        expect(screen.getByText('Any')).toBeInTheDocument()

        await userEvent.click(screen.getByText('All'))

        const inner = logic.values.filterGroup.values[0] as UniversalFiltersGroup
        expect(inner.type).toBe(FilterLogicalOperator.And)

        logic.unmount()
    })

    it('renders active filters below the filter picker', () => {
        const logic = issueFiltersLogic({ logicKey: LOGIC_KEY })
        logic.mount()
        logic.actions.setFilterGroup({
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values: [firefoxFilter] }],
        })

        render(
            <Provider>
                <BindLogic logic={issueFiltersLogic} props={{ logicKey: LOGIC_KEY }}>
                    <FilterGroup />
                </BindLogic>
            </Provider>
        )

        const filterPickerButton = screen.getByText('Add filter')
        const activeFilters = screen.getByTestId('error-tracking-active-filters')

        expect(filterPickerButton).not.toContainElement(activeFilters)
        expect(
            filterPickerButton.compareDocumentPosition(activeFilters) & Node.DOCUMENT_POSITION_FOLLOWING
        ).toBeTruthy()

        logic.unmount()
    })

    it('opens the filter picker directly to the main category', async () => {
        const logic = issueFiltersLogic({ logicKey: LOGIC_KEY })
        logic.mount()

        render(
            <Provider>
                <BindLogic logic={issueFiltersLogic} props={{ logicKey: LOGIC_KEY }}>
                    <FilterGroup />
                </BindLogic>
            </Provider>
        )

        await userEvent.click(screen.getByText('Add filter'))

        expect(await screen.findByText('Choose filter')).toBeInTheDocument()
        expect(screen.queryByText('New filter…')).not.toBeInTheDocument()

        logic.unmount()
    })
})
