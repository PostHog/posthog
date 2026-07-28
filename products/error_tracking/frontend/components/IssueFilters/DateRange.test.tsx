import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DateRangeFilter } from './DateRange'
import { issueFiltersLogic } from './issueFiltersLogic'

const LOGIC_KEY = 'test'

describe('DateRangeFilter', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/quick_filters/': { results: [] },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('updates the issue date range from the lemon-skinned Quill filter', async () => {
        const logic = issueFiltersLogic({ logicKey: LOGIC_KEY })
        logic.mount()

        render(
            <Provider>
                <BindLogic logic={issueFiltersLogic} props={{ logicKey: LOGIC_KEY }}>
                    <DateRangeFilter />
                </BindLogic>
            </Provider>
        )

        await userEvent.click(screen.getByText('Last 7 days'))

        const filter = document.querySelector('[data-attr="quill-date-filter"]')
        expect(filter).toBeInTheDocument()
        expect(filter?.closest('[data-lemon-skin="true"]')).toBeInTheDocument()

        await userEvent.click(await screen.findByText('30d'))

        expect(logic.values.dateRange).toEqual({ date_from: '-30d', date_to: null })

        logic.unmount()
    })
})
