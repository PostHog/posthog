import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY, issueFiltersLogic } from '../IssueFilters/issueFiltersLogic'
import { ContextDisplay } from './ContextDisplay'

describe('ContextDisplay', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/environments/:team_id/quick_filters/': { results: [] } } })
        initKeaTests()
    })

    afterEach(cleanup)

    it.each([
        ...[undefined, null, ''].map((value) => ({
            hiddenRow: 'Mobile operating system',
            value,
            properties: { $os: 'Mac OS X', $os_version: '10.15.7', $os_name: value },
            shownValue: 'Mac OS X 10.15.7',
        })),
        ...[null, ''].map((value) => ({
            hiddenRow: 'User agent',
            value,
            properties: { $user_agent: value, $current_url: 'https://example.com/orders' },
            shownValue: 'https://example.com/orders',
        })),
    ])('hides the $hiddenRow row when its value is $value', ({ hiddenRow, properties, shownValue }) => {
        render(
            <Provider>
                <ContextDisplay loading={false} properties={properties} additionalProperties={{}} />
            </Provider>
        )

        expect(screen.queryByText(hiddenRow)).not.toBeInTheDocument()
        expect(screen.getByText(shownValue)).toBeInTheDocument()
    })

    it.each([
        { version: undefined, displayedValue: 'iOS' },
        { version: '18.0', displayedValue: 'iOS 18.0' },
    ])('filters by the mobile OS name when its version is $version', ({ version, displayedValue }) => {
        render(
            <Provider>
                <ContextDisplay
                    loading={false}
                    properties={{ $os_name: 'iOS', $os_version: version }}
                    additionalProperties={{}}
                />
            </Provider>
        )

        expect(screen.getByText(displayedValue)).toBeInTheDocument()
        const row = screen.getByText('Mobile operating system').closest('tr')!
        fireEvent.click(within(row).getAllByRole('button')[0])

        const filters = issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY })
        expect(filters.values.filterGroup.values).toEqual([
            expect.objectContaining({
                values: [
                    {
                        key: '$os_name',
                        type: PropertyFilterType.Event,
                        operator: PropertyOperator.Exact,
                        value: ['iOS'],
                    },
                ],
            }),
        ])
    })
})
