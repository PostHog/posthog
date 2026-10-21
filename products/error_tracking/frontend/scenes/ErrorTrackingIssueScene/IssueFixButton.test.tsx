import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { newInternalTab } from 'lib/utils/newInternalTab'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { IssueFixButton } from './IssueFixButton'

jest.mock('lib/utils/newInternalTab', () => ({ newInternalTab: jest.fn() }))

const ISSUE_ID = '11111111-1111-4111-8111-111111111111'

describe('IssueFixButton', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    afterEach(cleanup)

    it.each([
        { connected: false, destination: 'Connect GitHub to fix this issue' },
        { connected: true, destination: null },
    ])('opens the right next step when GitHub connected is $connected', async ({ connected, destination }) => {
        useMocks({
            get: {
                '/api/projects/:team_id/integrations': {
                    results: connected ? [{ id: 1, kind: 'github', display_name: 'Example' }] : [],
                },
            },
        })
        initKeaTests()
        render(
            <Provider>
                <IssueFixButton issueId={ISSUE_ID} />
            </Provider>
        )
        const button = screen.getByText('Fix')
        await waitFor(() => expect(button).toBeEnabled())
        await userEvent.click(button)

        if (destination) {
            expect(await screen.findByText(destination)).toBeVisible()
            expect(newInternalTab).not.toHaveBeenCalled()
            const connect = screen.getByText('Connect GitHub')
            expect(connect.closest('a')).toHaveAttribute(
                'href',
                expect.stringContaining(`next=%2Ferror-tracking%2F${ISSUE_ID}`)
            )
        } else {
            expect(newInternalTab).toHaveBeenCalledWith(expect.stringContaining(encodeURIComponent(ISSUE_ID)))
            expect(decodeURIComponent((newInternalTab as jest.Mock).mock.calls[0][0])).toContain('draft pull request')
            expect(screen.queryByText('Connect GitHub to fix this issue')).not.toBeInTheDocument()
        }
    })
})
