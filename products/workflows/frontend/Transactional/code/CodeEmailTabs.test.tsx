import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CodeEmailApi } from 'products/messaging/frontend/generated/api.schemas'

import { codeEmailLogic } from './codeEmailLogic'
import { CodeEmailTabs } from './CodeEmailTabs'

// The summary table needs metric queries to draw its issue tags, so a stand-in exposes one tag's click.
// WorkflowMetrics, which turns that click into a drilldown, stays real.
jest.mock('../../Workflows/WorkflowMetricsSummary', () => ({
    WorkflowMetricsSummary: ({ onMetricClick }: { onMetricClick?: (metric: string) => void }) => (
        <button onClick={() => onMetricClick?.('email_bounced_transient')}>3 soft bounced</button>
    ),
}))

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

const BANNER = "This email's metrics and sends couldn't load. Check your connection and try again."

describe('CodeEmailTabs', () => {
    let logic: ReturnType<typeof codeEmailLogic.build>

    const mocks = (workflow: () => [number, unknown]): Parameters<typeof useMocks>[0] => ({
        get: {
            '/api/projects/:team_id/transactional_code_emails/:id/': codeEmail,
            '/api/environments/:team_id/hog_flows/:id/': workflow,
        },
        post: { '/api/environments/:team_id/query/': { results: [] } },
    })

    const renderTabs = (): void => {
        initKeaTests()
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

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('shows a retry on metrics and sends while the workflow fails to load, and the content once it loads', async () => {
        let workflowAnswers = 0
        useMocks(
            mocks(() =>
                ++workflowAnswers === 1 ? [500, { detail: 'Unavailable' }] : [200, { id: 'flow-id', actions: [] }]
            )
        )
        renderTabs()

        await screen.findByText(BANNER)
        fireEvent.click(screen.getByText('Sends'))
        expect(screen.getByText(BANNER)).toBeInTheDocument()
        fireEvent.click(screen.getByText('API'))
        expect(screen.queryByText(BANNER)).not.toBeInTheDocument()
        expect(document.querySelector('[data-attr=code-email-api-example]')).toHaveTextContent('password-reset')

        fireEvent.click(screen.getByText('Metrics'))
        await act(async () => {
            fireEvent.click(screen.getAllByText('Try again')[0])
        })

        await waitFor(() => expect(screen.queryByText(BANNER)).not.toBeInTheDocument())
        expect(workflowAnswers).toBe(2)
    })

    it('opens the sends behind a clicked email metric on this page, also when the link is opened again', async () => {
        useMocks(mocks(() => [200, { id: 'flow-id', actions: [] }]))
        renderTabs()
        router.actions.push(urls.transactionalCodeEmail('email-id'))
        const page = router.values.location.pathname

        fireEvent.click(await screen.findByText('3 soft bounced'))

        expect(logic.values.tab).toEqual('sends')
        expect(router.values.location.pathname).toEqual(page)
        expect(router.values.searchParams).toMatchObject({ inv_search: 'Transient bounce' })

        cleanup()
        logic.unmount()
        expect(codeEmailLogic.findMounted({ id: 'email-id' })).toBeNull()
        logic = codeEmailLogic({ id: 'email-id' })
        logic.mount()
        expect(logic.values.tab).toEqual('sends')
    })

    it('offers no re-run of a sensitive email, whose sends keep no content', async () => {
        useMocks(mocks(() => [200, { id: 'flow-id', actions: [] }]))
        renderTabs()

        fireEvent.click(await screen.findByText('Sends'))

        expect((await screen.findByText('Re-run…')).closest('button')).toHaveAttribute('aria-disabled', 'true')
    })
})
