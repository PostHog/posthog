import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { TransactionalEmailsTable } from './TransactionalEmailsTable'

const codeEmail = (key: string, userAccessLevel: AccessControlLevel): CodeEmailApi => ({
    id: `id-${key}`,
    key,
    hog_flow_id: `flow-${key}`,
    description: '',
    tags: ['auth'],
    sensitive: true,
    source_url: null,
    source_origin: null,
    created_at: '2026-01-01T00:00:00Z',
    user_access_level: userAccessLevel,
})

describe('TransactionalEmailsTable', () => {
    afterEach(cleanup)

    it.each([
        ['a workflow editor who can only view this email', AccessControlLevel.Editor, AccessControlLevel.Viewer, 0],
        ['a workflow viewer who can edit this email', AccessControlLevel.Viewer, AccessControlLevel.Editor, 1],
    ])(
        'lets %s edit its tags only with editor access to the email',
        async (_who, projectLevel, emailLevel, editButtons) => {
            useMocks({
                get: {
                    '/api/projects/:team_id/messaging_templates/': { results: [] },
                    '/api/projects/:team_id/transactional_code_emails/': [codeEmail('password-reset', emailLevel)],
                    '/api/projects/:team_id/tags': [],
                },
            })
            initKeaTests()
            const context = window.POSTHOG_APP_CONTEXT!
            window.POSTHOG_APP_CONTEXT = {
                ...context,
                resource_access_control: {
                    ...context.resource_access_control,
                    [AccessControlResourceType.Workflow]: projectLevel,
                },
            }
            const { container } = render(
                <Provider>
                    <TransactionalEmailsTable />
                </Provider>
            )

            await waitFor(() =>
                expect(container.querySelector('[data-attr=transactional-emails-table]')).toHaveTextContent(
                    'password-reset'
                )
            )

            const row = container.querySelector('[data-attr=transactional-emails-table] tbody tr')!
            expect(row.querySelectorAll('[data-attr=button-add-tag]')).toHaveLength(editButtons)
        }
    )

    it('says the emails failed to load instead of showing the first-run intro, and loads them on retry', async () => {
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
                '/api/projects/:team_id/transactional_code_emails/': [],
                '/api/projects/:team_id/tags': [],
            },
        })
        initKeaTests()
        const { container } = render(
            <Provider>
                <TransactionalEmailsTable />
            </Provider>
        )

        expect(
            await screen.findByText("Your emails couldn't load. Check your connection and try again.")
        ).toBeInTheDocument()
        expect(screen.queryByText(/Use them for emails a person triggers/)).not.toBeInTheDocument()

        templatesLoad = 'succeeds'
        fireEvent.click(container.querySelector('[data-attr=transactional-emails-templates-retry]')!)

        expect(await screen.findByText('Receipt')).toBeInTheDocument()
        expect(screen.queryByText(/couldn't load/)).not.toBeInTheDocument()
    })
})
