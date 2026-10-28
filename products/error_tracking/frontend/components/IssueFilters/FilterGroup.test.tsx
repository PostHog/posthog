import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { recentTaxonomicFiltersLogic } from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

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

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
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

    it('renders the compact picker as an icon after active filters', () => {
        const logic = issueFiltersLogic({ logicKey: LOGIC_KEY })
        logic.mount()
        logic.actions.setFilterGroup({
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values: [firefoxFilter] }],
        })

        render(
            <Provider>
                <BindLogic logic={issueFiltersLogic} props={{ logicKey: LOGIC_KEY }}>
                    <FilterGroup activeFiltersInline iconOnly />
                </BindLogic>
            </Provider>
        )

        const filterPickerButton = screen.getByLabelText('Add filter')
        const activeFilters = screen.getByTestId('error-tracking-active-filters')

        expect(filterPickerButton).not.toHaveTextContent('Add filter')
        expect(
            activeFilters.compareDocumentPosition(filterPickerButton) & Node.DOCUMENT_POSITION_FOLLOWING
        ).toBeTruthy()

        logic.unmount()
    })

    it('does not open the filter config for a filter added from a preview', async () => {
        const logic = issueFiltersLogic({ logicKey: LOGIC_KEY })
        logic.mount()

        render(
            <Provider>
                <BindLogic logic={issueFiltersLogic} props={{ logicKey: LOGIC_KEY }}>
                    <FilterGroup />
                </BindLogic>
            </Provider>
        )

        logic.actions.addPropertyFilter('$browser', 'Chrome', PropertyOperator.Exact, false)

        expect(await screen.findByText(/Chrome/)).toBeInTheDocument()
        expect(screen.queryByText('Choose filter')).not.toBeInTheDocument()

        logic.unmount()
    })

    it('opens the classic filter picker', async () => {
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

        expect(await screen.findByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()

        logic.unmount()
    })

    it('opens a menu with the extra rows and an entry into the classic filter picker', async () => {
        const logic = issueFiltersLogic({ logicKey: LOGIC_KEY })
        logic.mount()

        render(
            <Provider>
                <BindLogic logic={issueFiltersLogic} props={{ logicKey: LOGIC_KEY }}>
                    <FilterGroup
                        menuItems={<span>Extra menu row</span>}
                        renderControls={({ filterPicker }) => filterPicker}
                    />
                </BindLogic>
            </Provider>
        )

        await userEvent.click(screen.getByText('Add filter'))

        expect(await screen.findByText('Extra menu row')).toBeInTheDocument()
        expect(screen.queryByTestId('taxonomic-filter-searchfield')).not.toBeInTheDocument()

        const addFilterEntries = screen.getAllByText('Add filter')
        await userEvent.click(addFilterEntries[addFilterEntries.length - 1])

        expect(await screen.findByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()

        logic.unmount()
    })

    it('opens the value editor and adds a pill when custom controls initially have no filters', async () => {
        const logic = issueFiltersLogic({ logicKey: LOGIC_KEY })
        logic.mount()

        render(
            <Provider>
                <BindLogic logic={issueFiltersLogic} props={{ logicKey: LOGIC_KEY }}>
                    <FilterGroup
                        renderControls={({ filterPicker, activeFilters }) => (
                            <>
                                {filterPicker}
                                {activeFilters}
                            </>
                        )}
                    />
                </BindLogic>
            </Provider>
        )

        await userEvent.click(screen.getByText('Add filter'))
        await userEvent.click(await screen.findByText('Issue severity'))

        const valueEditor = (await screen.findByText('Enter value...')).closest('.Popover')
        await waitFor(() => expect(valueEditor).toHaveClass('Popover--enter-active'))
        expect(screen.getByTestId('error-tracking-active-filters')).toHaveTextContent('Issue severity')
        await waitFor(() => expect(screen.queryByTestId('taxonomic-filter-searchfield')).not.toBeInTheDocument())

        const inner = logic.values.filterGroup.values[0] as UniversalFiltersGroup
        expect(inner.values).toContainEqual(
            expect.objectContaining({ key: 'severity', type: PropertyFilterType.ErrorTrackingIssue })
        )

        logic.unmount()
    })

    it('opens the value editor and adds a pill for a recent issue property', async () => {
        const recents = recentTaxonomicFiltersLogic.build()
        recents.mount()
        recents.actions.clearRecentFilters()
        recents.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.ErrorTrackingIssues,
            groupName: 'Issues',
            value: 'severity',
            item: { name: 'severity' },
        })

        const logic = issueFiltersLogic({ logicKey: LOGIC_KEY })
        logic.mount()

        render(
            <Provider>
                <BindLogic logic={issueFiltersLogic} props={{ logicKey: LOGIC_KEY }}>
                    <FilterGroup
                        renderControls={({ filterPicker, activeFilters }) => (
                            <>
                                {filterPicker}
                                {activeFilters}
                            </>
                        )}
                    />
                </BindLogic>
            </Provider>
        )

        await userEvent.click(screen.getByText('Add filter'))
        const recentIssueRow = await screen.findByTestId('prop-filter-recent_filters-0')
        expect(recentIssueRow).toHaveTextContent('Issue severity')
        await userEvent.click(recentIssueRow)

        const valueEditor = (await screen.findByText('Enter value...')).closest('.Popover')
        await waitFor(() => expect(valueEditor).toHaveClass('Popover--enter-active'))
        expect(screen.getByTestId('error-tracking-active-filters')).toHaveTextContent('Issue severity')

        logic.unmount()
        recents.unmount()
    })
})
