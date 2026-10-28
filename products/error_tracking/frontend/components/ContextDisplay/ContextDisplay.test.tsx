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

    it.each([undefined, null, ''])('hides the mobile OS row when its name is %p', (osName) => {
        render(
            <Provider>
                <ContextDisplay
                    loading={false}
                    properties={{ $os: 'Mac OS X', $os_version: '10.15.7', $os_name: osName }}
                    additionalProperties={{}}
                />
            </Provider>
        )

        expect(screen.queryByText('Mobile operating system')).not.toBeInTheDocument()
        expect(screen.getByText('Mac OS X 10.15.7')).toBeInTheDocument()
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
