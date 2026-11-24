/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TransactionalEmailResults } from './TransactionalEmailResults'

const TEMPLATES = '/api/projects/:team_id/messaging_templates/'
const CODE_EMAILS = '/api/projects/:team_id/transactional_code_emails/'
const RESPONSES: Record<string, unknown> = {
    [TEMPLATES]: { count: 1, results: [{ id: 'tpl-1', name: 'Order receipt', transactional_hog_flow_id: 'flow-1' }] },
    [CODE_EMAILS]: [{ id: 'code-9', key: 'password-changed', hog_flow_id: 'flow-9' }],
}

describe('TransactionalEmailResults', () => {
    afterEach(() => cleanup())

    it.each([
        ['the code emails', CODE_EMAILS, 'password-changed', 'Order receipt'],
        ['the templates', TEMPLATES, 'Order receipt', 'password-changed'],
    ])(
        'brings back %s that failed to load when Try again is clicked',
        async (_list, failingPath, recovered, loaded) => {
            let failingRequests = 0
            const respond = (path: string) => () => {
                if (path === failingPath) {
                    failingRequests += 1
                    if (failingRequests === 1) {
                        return [500, { detail: 'Server error' }]
                    }
                }
                return [200, RESPONSES[path]]
            }
            useMocks({
                get: {
                    [TEMPLATES]: respond(TEMPLATES),
                    [CODE_EMAILS]: respond(CODE_EMAILS),
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
            fireEvent.click(screen.getByText('Choose an email'))
            expect(await screen.findByText(loaded)).toBeInTheDocument()
            expect(screen.queryByText(recovered)).not.toBeInTheDocument()

            fireEvent.click(container.querySelector(retry)!)

            expect(await screen.findByText(recovered)).toBeInTheDocument()
            expect(screen.getByText(loaded)).toBeInTheDocument()
            expect(container.querySelector(retry)).not.toBeInTheDocument()
        }
    )
})
