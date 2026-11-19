import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { codeEmailLogic } from './codeEmailLogic'
import { CodeEmailTabs } from './CodeEmailTabs'

const codeEmail: CodeEmailApi = {
    id: 'email-id',
    key: 'password-reset',
    hog_flow_id: 'flow-id',
    description: '',
    tags: [],
    sensitive: true,
    source_url: null,
    source_origin: null,
    created_at: '2026-01-01T00:00:00Z',
    user_access_level: 'editor',
}

const BANNER = "This email's metrics and run logs couldn't load. Check your connection and try again."

const TAGGING_OFF_TEAM = {
    ...MOCK_DEFAULT_TEAM,
    workflows_config: { capture_workflows_engagement_events: true, email_workflow_run_link_tag_enabled: false },
}

describe('CodeEmailTabs', () => {
    let logic: ReturnType<typeof codeEmailLogic.build>

    let sendRequests: Record<string, string>[]
    let sends: Record<string, string>[]

    const mocks = (workflow: () => [number, unknown]): Parameters<typeof useMocks>[0] => ({
        get: {
            '/api/organizations/:organization_id/projects/:id/': TAGGING_OFF_TEAM,
            '/api/projects/:team_id/transactional_code_emails/:id/': codeEmail,
            '/api/environments/:team_id/hog_flows/:id/': workflow,
            '/api/projects/:team_id/transactional_email_log/impact/': {
                sent: 10,
                delivered: 9,
                opened: 5,
                clicked: 2,
                not_clicked: 7,
                untracked: 0,
                window_days: 7,
                after_click: null,
                without_click: null,
            },
            '/api/projects/:team_id/transactional_email_log/': ({ request }) => {
                sendRequests.push(Object.fromEntries(new URL(request.url).searchParams))
                return [200, { results: sends, has_more: false }]
            },
        },
        post: {
            '/api/environments/:team_id/query/:query_kind/': async ({ request }) => {
                const { query } = ((await request.json()) as { query: { query: string } }).query
                const isEmailTotals = query.includes('instance_id, metric_name') && query.includes('email_bounced_hard')
                return [
                    200,
                    {
                        results: isEmailTotals
                            ? [
                                  [10, 'email-step', 'email_sent'],
                                  [3, 'email-step', 'email_bounced_transient'],
                              ]
                            : [],
                    },
                ]
            },
        },
    })

    const mountTabs = (): void => {
        logic = codeEmailLogic({ id: 'email-id' })
        logic.mount()
        render(
            <Provider>
                <BindLogic logic={codeEmailLogic} props={{ id: 'email-id' }}>
                    <CodeEmailTabs codeEmail={codeEmail} />
                </BindLogic>
            </Provider>
        )
    }

    const renderTabs = ({
        sendLinks = true,
        quillFilters = false,
        impact = false,
    }: { sendLinks?: boolean; quillFilters?: boolean; impact?: boolean } = {}): void => {
        sendRequests = []
        sends = [
            {
                message_id: 'msg-1',
                recipient: 'ada@example.com',
                status: 'bounced',
                created_at: '2026-03-14T10:00:00Z',
            },
        ]
        initKeaTests(true, TAGGING_OFF_TEAM)
        featureFlagLogic.mount()
        const flags = {
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_LINKS]: sendLinks,
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: quillFilters,
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_IMPACT]: impact,
        }
        featureFlagLogic.actions.setFeatureFlags(
            Object.entries(flags)
                .filter(([, on]) => on)
                .map(([flag]) => flag),
            flags
        )
        mountTabs()
    }

    const reopenTabs = (): void => {
        cleanup()
        logic.unmount()
        mountTabs()
    }

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('shows a retry on metrics and run logs while the workflow fails to load, and the content once it loads', async () => {
        let workflowAnswers = 0
        useMocks(
            mocks(() =>
                ++workflowAnswers === 1
                    ? [500, { detail: 'Unavailable' }]
                    : [
                          200,
                          {
                              id: 'flow-id',
                              actions: [
                                  {
                                      id: 'email-step',
                                      name: 'Password reset email',
                                      type: 'function_email',
                                      config: {},
                                  },
                              ],
                          },
                      ]
            )
        )
        renderTabs()

        await screen.findByText(BANNER)
        fireEvent.click(screen.getByText('Run logs'))
        expect(screen.getByText(BANNER)).toBeInTheDocument()
        fireEvent.click(screen.getByText('API'))
        expect(screen.queryByText(BANNER)).not.toBeInTheDocument()
        expect(document.querySelector('[data-attr=code-email-api-example]')).toHaveTextContent('password-reset')

        fireEvent.click(screen.getByText('Metrics'))
        await act(async () => {
            fireEvent.click(screen.getAllByText('Try again')[0])
        })

        expect(await screen.findByText(/^3 soft bounced/)).toBeInTheDocument()
        expect(screen.queryByText(BANNER)).not.toBeInTheDocument()
    })

    it("lists this email's sends, each linked to its page with the filters to come back to", async () => {
        useMocks(mocks(() => [200, { id: 'flow-id', actions: [] }]))
        renderTabs()
        router.actions.push(urls.transactionalCodeEmail('email-id'), { tab: 'sends', status: 'bounced' })

        const recipient = await screen.findByText('ada@example.com')

        expect(sendRequests.at(-1)).toMatchObject({ workflow_id: 'flow-id', status: 'bounced' })
        expect(recipient.closest('a')?.getAttribute('href')).toMatch(/\/transactional\/log\/msg-1\?status=bounced$/)
    })

    it('narrows the sends to a reason picked from the filter menu, and widens them again for any reason', async () => {
        useMocks(mocks(() => [200, { id: 'flow-id', actions: [] }]))
        renderTabs({ quillFilters: true })
        router.actions.push(urls.transactionalCodeEmail('email-id'), { tab: 'sends', status: 'bounced' })
        await screen.findByText('ada@example.com')

        fireEvent.click(document.querySelector('[data-attr=transactional-email-log-filter-menu]')!)
        fireEvent.click(await screen.findByText('Reason'))
        fireEvent.click(await screen.findByText('Hard bounce'))
        await waitFor(() => expect(sendRequests.at(-1)).toMatchObject({ status: 'bounced', reason: 'hard' }))
        fireEvent.click(await screen.findByText('Any reason'))
        await waitFor(() => expect(sendRequests.at(-1)).not.toHaveProperty('reason'))
    })

    it('tells the reader this email had no sends, not that no sends match a filter, once its status filter is cleared', async () => {
        useMocks(mocks(() => [200, { id: 'flow-id', actions: [] }]))
        renderTabs()
        sends = []
        router.actions.push(urls.transactionalCodeEmail('email-id'), { tab: 'sends', status: 'bounced' })
        expect(await screen.findByText('No sends match these filters')).toBeInTheDocument()

        router.actions.push(urls.transactionalCodeEmail('email-id'), { tab: 'sends' })

        expect(await screen.findByText(/This email had no sends in this period/)).toBeInTheDocument()
        expect(sendRequests.at(-1)).toMatchObject({ workflow_id: 'flow-id' })
    })

    it('opens the sends behind a clicked email metric on this page, also when the link is opened again, but the run logs from a link saved before the Sends list until the reader picks Sends', async () => {
        useMocks(
            mocks(() => [
                200,
                {
                    id: 'flow-id',
                    actions: [{ id: 'email-step', name: 'Password reset email', type: 'function_email', config: {} }],
                },
            ])
        )
        renderTabs()
        router.actions.push(urls.transactionalCodeEmail('email-id'))
        const page = router.values.location.pathname

        fireEvent.click(await screen.findByText(/^3 soft bounced/))

        const reasonFilter = (): Element | null =>
            document.querySelector('[data-attr=transactional-email-log-reason-filter]')
        await waitFor(() => expect(reasonFilter()).toHaveTextContent('Soft bounce'))
        expect(router.values.location.pathname).toEqual(page)
        await waitFor(() => expect(sendRequests.at(-1)).toMatchObject({ status: 'bounced', reason: 'soft' }))

        reopenTabs()
        await waitFor(() => expect(reasonFilter()).toHaveTextContent('Soft bounce'))

        fireEvent.click(reasonFilter()!)
        fireEvent.click(await screen.findByText('Hard bounce'))
        await waitFor(() => expect(sendRequests.at(-1)).toMatchObject({ status: 'bounced', reason: 'hard' }))
        fireEvent.click(reasonFilter()!)
        fireEvent.click(await screen.findByText('Any reason'))
        await waitFor(() => expect(sendRequests.at(-1)).not.toHaveProperty('reason'))
        expect(sendRequests.at(-1)).toMatchObject({ status: 'bounced' })

        router.actions.push(page, { tab: 'sends', inv_search: 'Permanent bounce' })
        expect(await screen.findByText('Re-run…')).toBeInTheDocument()
        expect(screen.queryByText('ada@example.com')).not.toBeInTheDocument()

        fireEvent.click(screen.getByText('Sends'))
        expect(await screen.findByText('ada@example.com')).toBeInTheDocument()
        reopenTabs()
        expect(await screen.findByText('ada@example.com')).toBeInTheDocument()

        router.actions.push(page, { tab: 'sends', inv_search: 'Transient bounce' })
        expect(await screen.findByText('Re-run…')).toBeInTheDocument()
    })

    it('keeps the run logs on the Sends tab without the send links flag, for a clicked email metric and a saved Sends link', async () => {
        useMocks(
            mocks(() => [
                200,
                {
                    id: 'flow-id',
                    actions: [{ id: 'email-step', name: 'Password reset email', type: 'function_email', config: {} }],
                },
            ])
        )
        renderTabs({ sendLinks: false })
        router.actions.push(urls.transactionalCodeEmail('email-id'))

        fireEvent.click(await screen.findByText(/^3 soft bounced/))

        expect(await screen.findByText('Re-run…')).toBeInTheDocument()
        expect(router.values.searchParams).toMatchObject({ inv_search: 'Transient bounce' })

        router.actions.push(urls.transactionalCodeEmail('email-id'), { tab: 'sends' })
        expect(await screen.findByText('Re-run…')).toBeInTheDocument()
        expect(screen.queryByText('Run logs')).not.toBeInTheDocument()
        expect(screen.queryByText('ada@example.com')).not.toBeInTheDocument()
    })

    it('links the Impact session step of a sensitive code email to the link tagging setting, since a send can turn sensitivity off', async () => {
        useMocks(mocks(() => [200, { id: 'flow-id', actions: [] }]))
        renderTabs({ impact: true })

        fireEvent.click(await screen.findByText('Impact'))

        expect((await screen.findByText('Needs link tagging')).closest('a')).toBeInTheDocument()
    })

    it('offers no re-run of a sensitive email, whose sends keep no content', async () => {
        useMocks(mocks(() => [200, { id: 'flow-id', actions: [] }]))
        renderTabs()

        fireEvent.click(await screen.findByText('Run logs'))

        expect((await screen.findByText('Re-run…')).closest('button')).toHaveAttribute('aria-disabled', 'true')
    })
})
