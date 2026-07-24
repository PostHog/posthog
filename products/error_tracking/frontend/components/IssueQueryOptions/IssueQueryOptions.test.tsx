import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { IssueSortButton } from './IssueQueryOptions'
import { issueQueryOptionsLogic } from './issueQueryOptionsLogic'

const LOGIC_KEY = 'test'

describe('IssueSortButton', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('opens the grouped sort options', async () => {
        render(
            <Provider>
                <BindLogic logic={issueQueryOptionsLogic} props={{ logicKey: LOGIC_KEY }}>
                    <IssueSortButton />
                </BindLogic>
            </Provider>
        )

        await userEvent.click(screen.getByText('Last seen'))

        expect(await screen.findByText('Sort by')).toBeInTheDocument()
        expect(screen.getByText('Direction')).toBeInTheDocument()
    })
})
