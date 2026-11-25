/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext, PreflightStatus } from '~/types'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { sendFromCodeGuideUrl } from './sendFromCode/sendFromCodeGuideUrl'
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
    afterEach(() => {
        cleanup()
        Reflect.deleteProperty(navigator, 'clipboard')
        Reflect.deleteProperty(window.POSTHOG_APP_CONTEXT ?? {}, 'preflight')
    })

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

    const loadFlags = (wizardOffered = false, codeSendsOn = true): void =>
        featureFlagLogic.actions.setFeatureFlags(
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_FROM_CODE, FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_WIZARD],
            {
                [FEATURE_FLAGS.WORKFLOWS_EMAIL_FROM_CODE]: codeSendsOn,
                [FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_WIZARD]: wizardOffered,
            }
        )

    const renderWithCodeSends = (
        get: Record<string, unknown>,
        {
            wizardOffered = false,
            selfHosted = false,
            flagsLoaded = true,
        }: { wizardOffered?: boolean; selfHosted?: boolean; flagsLoaded?: boolean } = {}
    ): ReturnType<typeof render> => {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:team_id/transactional_code_emails/': [],
                '/api/projects/:team_id/integrations/': { results: [] },
                '/api/projects/:team_id/tags': [],
                ...get,
            } as Record<string, any>,
        })
        if (!flagsLoaded) {
            window.localStorage.clear()
        }
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            preflight: { cloud: !selfHosted } as PreflightStatus,
        } as AppContext
        initKeaTests()
        if (flagsLoaded) {
            loadFlags(wizardOffered)
        }
        return render(
            <Provider>
                <TransactionalEmailsTable />
            </Provider>
        )
    }

    it.each([
        ['tells a cloud team with emails that transactional emails never wait for the sending allowance', false],
        ['says nothing about a sending allowance on a self-hosted instance, which has none', true],
    ])('%s', async (_case, selfHosted) => {
        renderWithCodeSends(
            {
                '/api/projects/:team_id/transactional_code_emails/': [
                    codeEmail('password-reset', AccessControlLevel.Editor),
                ],
            },
            { selfHosted }
        )
        expect(await screen.findByText('password-reset')).toBeInTheDocument()

        expect(
            Boolean(
                screen.queryByText(
                    "Transactional emails count toward your daily sending allowance and are still sent after it's used up."
                )
            )
        ).toBe(!selfHosted)
        expect(screen.queryByText('How sending allowances work')?.closest('a')?.getAttribute('href')).toBe(
            selfHosted
                ? undefined
                : 'https://posthog.com/docs/workflows/sending-reputation#do-transactional-emails-count-against-the-allowance'
        )
    })

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

        fireEvent.click(container.querySelector('[data-attr=send-from-code-set-up-domain]')!)
        expect(router.values.location.pathname).toMatch(new RegExp(`${urls.workflowsEmailDomain('new')}$`))
        expect(router.values.searchParams).toEqual({ from: 'transactional' })
    })

    it.each([
        ['leads with the Wizard command once it is offered', true, false, true],
        ['leads with the agent prompt until the Wizard command is offered', false, false, false],
        ['leads with the agent prompt on a self-hosted instance the Wizard cannot reach', true, true, false],
    ])('%s, with the code one click away', async (_case, wizardOffered, selfHosted, wizardShown) => {
        const { container } = renderWithCodeSends({}, { wizardOffered, selfHosted })
        await waitFor(() => {
            expect(container.querySelector('[data-attr=send-from-code-copy-agent-prompt]')).toBeInTheDocument()
            if (wizardShown) {
                expect(container.querySelector('[data-attr=wizard-command-block]')).toHaveTextContent(
                    'npx @posthog/wizard email'
                )
            }
        })
        if (!wizardShown) {
            expect(container.querySelector('[data-attr=wizard-command-block]')).not.toBeInTheDocument()
        }
        expect(screen.queryByText('Or use your own coding agent') !== null).toBe(wizardShown)
        expect(container.querySelector('[data-attr=send-from-code-snippet]')).not.toBeInTheDocument()

        const clipboard = {
            text: '',
            writeText: async (text: string): Promise<void> => {
                clipboard.text = text
            },
        }
        Object.defineProperty(navigator, 'clipboard', { value: clipboard, configurable: true })
        if (wizardShown) {
            const wizardButton = screen.getByLabelText('Copy wizard command')
            const promptButton = container.querySelector('[data-attr=send-from-code-copy-agent-prompt]')!
            expect(wizardButton.compareDocumentPosition(promptButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
            fireEvent.click(wizardButton)
            await waitFor(() => expect(clipboard.text).toBe('npx -y @posthog/wizard@latest email'))
        }

        fireEvent.click(container.querySelector('[data-attr=send-from-code-copy-agent-prompt]')!)
        await waitFor(() => expect(clipboard.text).toContain('PostHog project token: phc_default-team-api-token'))
        expect(clipboard.text).toContain('Leave out the from address.')

        fireEvent.click(container.querySelector('[data-attr=send-from-code-show-code]')!)

        expect(container.querySelector('[data-attr=send-from-code-snippet]')).toHaveTextContent('Node.js')
    })

    const receipt = {
        id: 'template-1',
        name: 'Receipt',
        transactional_hog_flow_id: 'flow-1',
        has_draft: false,
        tags: [],
    }

    it.each([
        ['opens the guide over the list', [receipt], [], 'Receipt', true],
        [
            'keeps the guide closed when the project already sends from code',
            [receipt],
            [codeEmail('welcome', AccessControlLevel.Editor)],
            'Receipt',
            false,
        ],
        ['shows the empty tab, which holds the guide already', [], [], 'Send your first email from code', false],
    ])('answers a link from the domain-ready card: %s', async (_case, templates, codeEmails, landmark, modalOpens) => {
        renderWithCodeSends({
            '/api/projects/:team_id/messaging_templates/': { results: templates },
            '/api/projects/:team_id/transactional_code_emails/': codeEmails,
        })
        expect(await screen.findByText(landmark)).toBeInTheDocument()
        await waitFor(() => expect(transactionalEmailsLogic.values.codeEmails).toHaveLength(codeEmails.length))
        act(() => router.actions.push(sendFromCodeGuideUrl()))

        await waitFor(() => expect(router.values.searchParams).toEqual({}))
        expect(screen.queryByText('Send an email from your code') !== null).toBe(modalOpens)
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

    it.each([
        ['opens the guide over the list once code sends turn out on', [receipt], 'Receipt', true, true],
        [
            'drops the link from an empty tab once code sends turn out off',
            [],
            'Create your first transactional email',
            false,
            false,
        ],
    ])(
        'holds a link from the domain-ready card until feature flags load, then %s',
        async (_case, templates, landmark, codeSendsOn, modalOpens) => {
            renderWithCodeSends(
                { '/api/projects/:team_id/messaging_templates/': { results: templates } },
                { flagsLoaded: false }
            )
            expect(await screen.findByText(landmark)).toBeInTheDocument()
            await waitFor(() => expect(transactionalEmailsLogic.values.codeEmails).toEqual([]))
            act(() => router.actions.push(sendFromCodeGuideUrl()))
            expect(router.values.searchParams).toEqual({ guide: 'send-from-code' })

            act(() => loadFlags(false, codeSendsOn))

            await waitFor(() => expect(router.values.searchParams).toEqual({}))
            expect(screen.queryByText('Send an email from your code') !== null).toBe(modalOpens)
        }
    )
})
