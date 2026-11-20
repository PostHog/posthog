/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TransactionalEmailResults } from './TransactionalEmailResults'

describe('TransactionalEmailResults', () => {
    afterEach(() => cleanup())

    it('brings back a code email that failed to load when Try again is clicked, keeping the templates', async () => {
        let codeEmailRequests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': {
                    count: 1,
                    results: [{ id: 'tpl-1', name: 'Order receipt', transactional_hog_flow_id: 'flow-1' }],
                },
                '/api/projects/:team_id/transactional_code_emails/': () => {
                    codeEmailRequests += 1
                    return codeEmailRequests === 1
                        ? [500, { detail: 'Server error' }]
                        : [200, [{ id: 'code-9', key: 'password-changed', hog_flow_id: 'flow-9' }]]
                },
                '/api/projects/:team_id/transactional_email_log/stats/': { results: [] },
                '/api/projects/:team_id/transactional_email_log/stats_over_time/': { results: [] },
            },
        })
        initKeaTests()
        const { container } = render(
            <Provider>
                <TransactionalEmailResults />
            </Provider>
        )

        const retry = '[data-attr=transactional-email-results-templates-retry]'
        await waitFor(() => expect(container.querySelector(retry)).toBeInTheDocument())
        fireEvent.click(container.querySelector(retry)!)
        await waitFor(() => expect(container.querySelector(retry)).not.toBeInTheDocument())
        fireEvent.click(screen.getByText('Choose an email'))

        expect(await screen.findByText('password-changed')).toBeInTheDocument()
        expect(screen.getByText('Order receipt')).toBeInTheDocument()
    })
})
