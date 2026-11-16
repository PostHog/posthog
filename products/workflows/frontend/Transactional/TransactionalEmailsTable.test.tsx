/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { transactionalEmailsLogic } from './transactionalEmailsLogic'
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

    it.each([
        ['leads with sending from code when code sends are on', true, 'Send your first email from code'],
        ['keeps the template intro when code sends are off', false, 'Create your first transactional email'],
    ])('%s in an empty tab', async (_case, codeSendsOn, heading) => {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:team_id/transactional_code_emails/': [],
                '/api/projects/:team_id/integrations/': { results: [] },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_EMAIL_FROM_CODE], {
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_FROM_CODE]: codeSendsOn,
        })
        render(
            <Provider>
                <TransactionalEmailsTable />
            </Provider>
        )

        expect(await screen.findByText(heading)).toBeInTheDocument()
    })

    const renderWithCodeSends = (get: Record<string, unknown>): ReturnType<typeof render> => {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:team_id/transactional_code_emails/': [],
                '/api/projects/:team_id/integrations/': { results: [] },
                '/api/projects/:team_id/tags': [],
                ...get,
            } as Record<string, any>,
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_EMAIL_FROM_CODE], {
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_FROM_CODE]: true,
        })
        return render(
            <Provider>
                <TransactionalEmailsTable />
            </Provider>
        )
    }

    it('keeps the first send from code on screen in the empty tab', async () => {
        jest.useFakeTimers()
        let stored: CodeEmailApi[] = []
        renderWithCodeSends({ '/api/projects/:team_id/transactional_code_emails/': () => [200, stored] })
        expect(await screen.findByText(/Waiting for your first send/)).toBeInTheDocument()

        stored = [codeEmail('welcome', AccessControlLevel.Editor)]
        await act(() => jest.advanceTimersByTimeAsync(10_000))

        expect(screen.getByText('PostHog got the first email from your code.')).toBeInTheDocument()
        jest.useRealTimers()
    })

    it('says a failed check right away instead of waiting quietly', async () => {
        jest.useFakeTimers()
        let listCalls = 0
        renderWithCodeSends({
            '/api/projects/:team_id/transactional_code_emails/': () =>
                ++listCalls === 1 ? [200, []] : [500, { detail: 'A server error occurred.' }],
        })

        expect(await screen.findByText(/Couldn't check for emails from your code. Trying again./)).toBeInTheDocument()
        jest.useRealTimers()
    })

    it('says the sending domain failed to load, and loads it on retry', async () => {
        let integrationsFail = true
        const { container } = renderWithCodeSends({
            '/api/projects/:team_id/integrations/': () =>
                integrationsFail ? [500, { detail: 'A server error occurred.' }] : [200, { results: [] }],
        })
        expect(await screen.findByText("Couldn't load your sending domain.")).toBeInTheDocument()

        integrationsFail = false
        fireEvent.click(container.querySelector('[data-attr=send-from-code-reload-domain]')!)

        expect(await screen.findByText(/Set up the domain you send from/)).toBeInTheDocument()
    })

    it('offers sending from code only once the templates loaded', async () => {
        let releaseTemplates: () => void = () => {}
        renderWithCodeSends({
            '/api/projects/:team_id/messaging_templates/': () =>
                new Promise((resolve) => {
                    releaseTemplates = () =>
                        resolve([
                            200,
                            {
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
                        ])
                }),
        })
        await waitFor(() => expect(transactionalEmailsLogic.values.codeEmails).toEqual([]))
        expect(screen.queryByText(/Your code can send any email/)).not.toBeInTheDocument()

        releaseTemplates()

        expect(await screen.findByText(/Your code can send any email/)).toBeInTheDocument()
    })
})
