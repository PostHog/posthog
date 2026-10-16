import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { DashboardType, SubscriptionType } from '~/types'

import { EditSubscription } from './EditSubscription'

const DASHBOARD = {
    id: 5,
    name: 'Weekly metrics',
    tiles: [
        { id: 1, insight: { id: 11, short_id: 'ins11', name: 'Pageviews' }, layouts: { sm: { x: 0, y: 0 } } },
        { id: 2, insight: { id: 12, short_id: 'ins12', name: 'Sessions' }, layouts: { sm: { x: 0, y: 1 } } },
    ],
} as unknown as DashboardType

const SLACK_INTEGRATION = {
    id: 7,
    kind: 'slack',
    config: { team: { id: '123', name: 'PostHog' } },
    display_name: 'PostHog',
    icon_url: '',
    created_at: '2022-01-01T00:09:00',
}

// Mirrors every field the API returns, including the null ones: a field the form renders but the
// response leaves null is where a controlled input can write itself a value.
const subscriptionFixture = (overrides: Partial<SubscriptionType>): SubscriptionType =>
    ({
        id: 1,
        title: 'Weekly dashboard snapshot',
        resource_type: 'dashboard',
        resource_name: 'Website',
        dashboard: 5,
        insight: null,
        insight_short_id: null,
        dashboard_export_insights: [11, 12],
        contexts: [],
        prompt: null,
        ai_prompt_config: {},
        ai_query_plan_status: null,
        frequency: 'weekly',
        interval: 1,
        byweekday: ['monday'],
        bysetpos: null,
        count: null,
        start_date: '2024-03-04T13:00:00.107000Z',
        until_date: null,
        next_delivery_date: '2024-03-11T13:00:00Z',
        created_at: '2024-03-01T09:30:00.000000Z',
        deleted: false,
        enabled: true,
        summary: 'sent every week on Monday',
        summary_enabled: false,
        summary_prompt_guide: '',
        integration_id: null,
        invite_message: null,
        delivery_config: { post_all_insights_in_main_message: false },
        ...overrides,
    }) as unknown as SubscriptionType

// The insight picker fills an empty selection and the destination picker selects the only
// connected workspace. Neither is an edit, so neither may arm the unsaved-changes prompt.
describe('EditSubscription unsaved changes', () => {
    const saveButton = (): HTMLButtonElement => screen.getByText('Save').closest('button') as HTMLButtonElement
    const isClean = (): boolean => saveButton().disabled || saveButton().getAttribute('aria-disabled') === 'true'

    afterEach(() => cleanup())

    it('shows a missing-subscription message after its request fails', async () => {
        useMocks({
            get: {
                '/api/environments/:team/subscriptions/1': () => [404, { detail: 'Not found' }],
                '/api/environments/:team/subscriptions': { count: 0, results: [] },
                '/api/projects/:team/subscriptions/1/deliveries/': { next: null, previous: null, results: [] },
                '/api/projects/:team/integrations': { count: 0, results: [] },
                '/api/projects/:team/integrations/:intId/channels': { channels: [] },
                '/api/environments/:team/subscriptions/summary_quota': {
                    active_count: 0,
                    limit: null,
                    at_limit: false,
                },
                '/api/organizations/@current/': MOCK_DEFAULT_ORGANIZATION,
                '/api/organizations/@current/members/': { count: 0, results: [] },
            },
        })
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)

        render(
            <Provider>
                <EditSubscription id={1} dashboard={DASHBOARD} onCancel={jest.fn()} onDelete={jest.fn()} />
            </Provider>
        )

        expect(await screen.findByText('Not found')).toBeInTheDocument()
    })

    it.each([
        [
            'an email destination',
            { target_type: 'email', target_value: 'subscriber@example.com', integration_id: null },
        ],
        ['a Slack destination', { target_type: 'slack', target_value: 'C1|#general', integration_id: 7 }],
        [
            'a Slack destination with no stored connection',
            { target_type: 'slack', target_value: 'C1|#general', integration_id: null },
        ],
    ])(
        'stays clean on open and after saving %s',
        async (_label, overrides) => {
            const subscription = subscriptionFixture(overrides as Partial<SubscriptionType>)
            useMocks({
                get: {
                    '/api/environments/:team/subscriptions/1': subscription,
                    '/api/environments/:team/subscriptions': { count: 0, results: [] },
                    '/api/projects/:team/subscriptions/1/deliveries/': { next: null, previous: null, results: [] },
                    '/api/projects/:team/integrations': { count: 1, results: [SLACK_INTEGRATION] },
                    '/api/projects/:team/integrations/:intId/channels': { channels: [] },
                    '/api/environments/:team/subscriptions/summary_quota': {
                        active_count: 0,
                        limit: null,
                        at_limit: false,
                    },
                    '/api/organizations/@current/': MOCK_DEFAULT_ORGANIZATION,
                    '/api/organizations/@current/members/': {
                        count: 1,
                        results: [
                            {
                                id: 'mem-1',
                                level: 8,
                                joined_at: '2022-01-01T00:09:00',
                                updated_at: '2022-01-01T00:09:00',
                                user: { ...MOCK_DEFAULT_USER, email: 'subscriber@example.com' },
                            },
                        ],
                    },
                },
                patch: { '/api/environments/:team/subscriptions/1': subscription },
            })
            initKeaTests()
            userLogic.mount()
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
            router.actions.push('/dashboard/5/subscriptions/1')

            render(
                <Provider>
                    <EditSubscription id={1} dashboard={DASHBOARD} onCancel={jest.fn()} onDelete={jest.fn()} />
                </Provider>
            )

            const name = await screen.findByPlaceholderText('e.g. Weekly team report', {}, { timeout: 10000 })
            expect(isClean()).toBe(true)

            await userEvent.type(name, ' renamed')
            await waitFor(() => expect(isClean()).toBe(false))

            await userEvent.click(saveButton())
            await waitFor(() => expect(isClean()).toBe(true), { timeout: 10000 })
        },
        30000
    )
})
