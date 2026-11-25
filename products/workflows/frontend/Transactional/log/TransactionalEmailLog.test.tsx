import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TransactionalEmailLog } from './TransactionalEmailLog'

describe('TransactionalEmailLog', () => {
    afterEach(cleanup)

    it('says the email filter is empty because the emails failed to load, and fills it on retry', async () => {
        let templatesLoad: 'fails' | 'succeeds' = 'fails'
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': () =>
                    templatesLoad === 'fails'
                        ? [500, { detail: 'A server error occurred.' }]
                        : [
                              200,
                              {
                                  count: 1,
                                  next: null,
                                  results: [
                                      {
                                          id: 'template-1',
                                          name: 'Receipt',
                                          transactional_hog_flow_id: 'flow-1',
                                          has_draft: false,
                                          tags: [],
                                      },
                                  ],
                              },
                          ],
                '/api/projects/:team_id/transactional_email_log/': { results: [], has_more: false },
            },
        })
        initKeaTests()
        const { container } = render(
            <Provider>
                <TransactionalEmailLog />
            </Provider>
        )

        expect(await screen.findByText(/you can't filter by email yet/)).toBeInTheDocument()

        templatesLoad = 'succeeds'
        fireEvent.click(container.querySelector('[data-attr=transactional-email-log-templates-retry]')!)
        await waitFor(() => expect(screen.queryByText(/couldn't load/)).not.toBeInTheDocument())

        fireEvent.click(container.querySelector('[data-attr=transactional-email-log-email-filter]')!)
        expect(await screen.findByText('Receipt')).toBeInTheDocument()
    })
})
