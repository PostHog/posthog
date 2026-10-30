import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'
import { useValues } from 'kea'

import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

import { expect } from 'storybook/test'

import type { InboxOnboardingDraftApi } from '../../../generated/api.schemas'
import { mockScoutSuggestionSet, mockScoutConfigs } from '../../__mocks__/scoutConfigs'
import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { InboxActivationPanel } from './InboxActivationPanel'
import { InboxOnboardingBanner } from './InboxOnboardingBanner'
import { InboxOnboardingEntry } from './InboxOnboardingEntry'
import { InboxSetupFlow } from './InboxSetupFlow'

const draft: InboxOnboardingDraftApi = {
    step: 'signals',
    sources: [
        { source_product: 'error_tracking', source_type: 'issue_created', enabled: true },
        { source_product: 'error_tracking', source_type: 'issue_reopened', enabled: true },
        { source_product: 'error_tracking', source_type: 'issue_spiking', enabled: true },
        { source_product: 'health_checks', source_type: 'health_issue', enabled: true },
    ],
    scanner_ids: ['11111111-1111-4111-8111-111111111111'],
    suggestions: [],

    automatic_implementation: false,
    implementation_priority: 'P1',
}

function projectMocks(
    hasData: boolean,
    membershipLevel: TeamMembershipLevel | null = TeamMembershipLevel.Admin
): ReturnType<typeof mswDecorator> {
    let team = {
        ...MOCK_DEFAULT_TEAM,
        ingested_event: hasData,
        session_recording_opt_in: hasData,
        autocapture_exceptions_opt_in: hasData,
        conversations_enabled: false,
        effective_membership_level: membershipLevel,
    }
    return mswDecorator({
        get: {
            '/api/projects/:id': () => [200, team],
            '/api/projects/:id/error_tracking/issues/exists/': { exists: hasData },
        },
        post: {
            '/api/projects/:id/product_enablement/': async ({ request }) => {
                const { products } = (await request.json()) as { products: string[] }
                team = {
                    ...team,
                    session_recording_opt_in: team.session_recording_opt_in || products.includes('session_replay'),
                    autocapture_exceptions_opt_in:
                        team.autocapture_exceptions_opt_in || products.includes('error_tracking'),
                    conversations_enabled: team.conversations_enabled || products.includes('conversations'),
                }
                return [200, {}]
            },
        },
    })
}

const meta: Meta<typeof InboxSetupFlow> = {
    title: 'Scenes-App/Inbox/Focused setup',
    component: InboxSetupFlow,
    parameters: {
        layout: 'fullscreen',
        mockDate: '2026-10-14',
        featureFlags: { [FEATURE_FLAGS.SELF_DRIVING_UBP]: true },
    },
    decorators: [
        (Story) => (
            <div className="h-dvh p-4">
                <Story />
            </div>
        ),
        projectMocks(true),
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports/available_reviewers/': {},
                '/api/projects/:id/signals/onboarding/': { draft, completed_at: null },
                '/api/projects/:id/signals/source_configs/': { results: [], next: null, count: 0 },
                '/api/projects/:id/event_definitions/': {
                    results: [{ name: '$exception', last_seen_at: '2026-01-01T00:00:00Z' }],
                    next: null,
                    count: 1,
                },
                '/api/projects/:id/vision/scanners/': {
                    results: [
                        {
                            id: '11111111-1111-4111-8111-111111111111',
                            name: 'Checkout scanner',
                            enabled: true,
                            emits_signals: false,
                        },
                    ],
                    next: null,
                    count: 1,
                },
                '/api/projects/:id/signals/scout/suggestions/': mockScoutSuggestionSet(),
                '/api/projects/:id/signals/scout/configs/': [],
                '/api/projects/:id/integrations/': { results: [], next: null, count: 0 },
                '/api/projects/:id/integrations/github/available_installations/': {
                    discovery_id: 'example',
                    discovered_at: '2026-01-01T00:00:00Z',
                    installations: [],
                    personal_github_connected: false,
                    personal_github_login: null,
                    personal_discovery_status: 'not_connected',
                },
                '/api/projects/:id/integrations/github/install_requests/': [],
            },
            post: {
                '/api/projects/:id/signals/scout/configs/sync/': [],
                '/api/projects/:id/signals/onboarding/': async ({ request }) => [
                    200,
                    { draft: await request.json(), completed_at: null },
                ],
            },
        }),
    ],
}

export default meta
type Story = StoryObj<typeof meta>

export const Signals: Story = {}
export const NarrowSignals: Story = {
    decorators: [
        (Story) => (
            <div className="h-full w-130">
                <Story />
            </div>
        ),
    ],
}
export const Scouts: Story = {
    render: () => <InboxOnboardingEntry />,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/onboarding/': {
                    draft: { ...draft, step: 'scouts' },
                    completed_at: null,
                },
            },
            post: {
                '/api/projects/:id/signals/onboarding/expose/': {
                    draft: { ...draft, step: 'scouts' },
                    completed_at: null,
                },
            },
        }),
    ],
}
export const Github: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/onboarding/': {
                    draft: { ...draft, step: 'github' },
                    completed_at: null,
                },
            },
        }),
    ],
}

export const GithubWithoutAutomaticImplementation: Story = {
    ...Github,
    parameters: { featureFlags: { [FEATURE_FLAGS.SELF_DRIVING_UBP]: false } },
}

export const NoProductsEnabled: Story = {
    decorators: [
        projectMocks(false),
        mswDecorator({
            get: {
                '/api/projects/:id/signals/onboarding/': { draft: null, completed_at: null },
                '/api/projects/:id/event_definitions/': { results: [], next: null, count: 0 },
                '/api/projects/:id/vision/scanners/': { results: [], next: null, count: 0 },
                '/api/projects/:id/signals/scout/configs/': [
                    { ...mockScoutConfigs[0], id: 'general', skill_name: 'signals-scout-general', enabled: false },
                ],
                '/api/projects/:id/signals/scout/suggestions/': mockScoutSuggestionSet({
                    status: 'low_activity',
                    items: [],
                }),
            },
            post: {
                '/api/projects/:id/signals/scout/configs/sync/': [
                    { ...mockScoutConfigs[0], id: 'general', skill_name: 'signals-scout-general', enabled: false },
                ],
            },
        }),
    ],
}

export const BuiltInScouts: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/onboarding/': {
                    draft: { ...draft, step: 'scouts' },
                    completed_at: null,
                },
                '/api/projects/:id/signals/scout/suggestions/': mockScoutSuggestionSet({
                    status: 'low_activity',
                    items: [],
                }),
                '/api/projects/:id/signals/scout/configs/': [],
            },
            post: {
                '/api/projects/:id/signals/scout/configs/sync/': [
                    'general',
                    'product-analytics',
                    'error-tracking',
                    'session-replay',
                    'replay-vision',
                    'ai-observability',
                    'conversations',
                    'health-checks',
                ].map((name) => ({
                    ...mockScoutConfigs[0],
                    id: `builtin-${name}`,
                    skill_name: `signals-scout-${name}`,
                    enabled: false,
                })),
            },
        }),
    ],
}

export const GithubAlreadyConnected: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/onboarding/': {
                    draft: { ...draft, step: 'github' },
                    completed_at: null,
                },
                '/api/projects/:id/integrations/': {
                    results: [
                        {
                            id: 1,
                            kind: 'github',
                            config: {},
                            display_name: 'example',
                            created_at: '2026-10-14',
                            icon_url: '',
                        },
                    ],
                    next: null,
                    count: 1,
                },
                '/api/projects/:id/integrations/1/github_repos/': {
                    repositories: [{ id: 1, name: 'app', full_name: 'example/app', can_push: true }],
                    has_more: false,
                    total: 1,
                },
            },
        }),
    ],
}

export const GithubAccessRequired: Story = {
    decorators: [
        projectMocks(true, null),
        mswDecorator({
            get: {
                '/api/projects/:id/signals/onboarding/': {
                    draft: { ...draft, step: 'github' },
                    completed_at: null,
                },
            },
            post: { '/api/projects/:id/integrations/request_access/': {} },
        }),
    ],
}

export const PausedReminder: Story = {
    name: 'Paused reminder',
    render: () => <InboxOnboardingBanner />,
    play: async ({ canvas }) => {
        await expect(canvas.findByText('Set up Self-Driving')).resolves.toBeVisible()
    },
    decorators: [
        mswDecorator({
            get: { '/api/projects/:id/signals/onboarding/': { draft: null, completed_at: null } },
        }),
    ],
}

let quickActivationCompleted = false

function QuickActivationPreview(): JSX.Element {
    const { completed } = useValues(inboxSetupLogic)
    return completed ? (
        <div className="mx-auto max-w-4xl p-6">
            <InboxActivationPanel />
        </div>
    ) : (
        <InboxOnboardingEntry />
    )
}

const quickGeneralScout = {
    ...mockScoutConfigs[0],
    skill_name: 'signals-scout-general',
    enabled: false,
    scout_origin: 'canonical',
}

export const QuickEntry = {
    name: 'Welcome with GitHub and manual setup',
    render: () => <QuickActivationPreview />,
    play: async ({ canvas }) => {
        await canvas.findByText('Connect GitHub')
        await expect(canvas.getByText('Start manually')).toBeVisible()
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/onboarding/': { draft: null, completed_at: null },
                '/api/projects/:id/signals/scout/configs/': [quickGeneralScout],
                '/api/projects/:id/signals/scout/suggestions/': {
                    status: 'empty',
                    generated_at: null,
                    model: '',
                    fleet_snapshot: [],
                    items: [],
                },
            },
            post: {
                '/api/projects/:id/signals/onboarding/expose/': { draft: null, completed_at: null },
                '/api/projects/:id/signals/scout/configs/sync/': [quickGeneralScout],
            },
        }),
    ],
} satisfies Story

export const NarrowWelcomeEntry: Story = {
    ...QuickEntry,
    name: 'Narrow welcome',
    decorators: [
        ...(QuickEntry.decorators ?? []),
        (Story) => (
            <div className="h-full w-130">
                <Story />
            </div>
        ),
    ],
}

export const GithubOptional: Story = {
    ...QuickEntry,
    name: 'GitHub-optional pilot',
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.SELF_DRIVING_GITHUB_OPTIONAL]: true,
        },
    },
    play: async ({ canvas }) => {
        await canvas.findByText('Activate Self-Driving')
        await expect(canvas.queryByText('Connect GitHub')).not.toBeInTheDocument()
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/onboarding/': {
                    draft: null,
                    completed_at: null,
                    github_optional_available: true,
                },
                '/api/projects/:id/signals/scout/configs/': [quickGeneralScout],
                '/api/projects/:id/integrations/': { results: [], next: null, count: 0 },
            },
        }),
    ],
}

export const QuickConnected: Story = {
    ...QuickEntry,
    name: 'Quick setup with GitHub connected',
    play: async ({ canvas }) => {
        // Nothing is prefetched for the welcome screen, so the button is enabled as soon as the project loads.
        const activate = (await canvas.findByText('Activate Self-Driving')).closest('button')
        await waitFor(() => expect(activate).toHaveAttribute('aria-disabled', 'false'))
        await expect(canvas.getByText('Start manually')).toBeVisible()
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/onboarding/': () => ({
                    draft: null,
                    completed_at: quickActivationCompleted ? '2026-10-14T00:00:00Z' : null,
                    ...(quickActivationCompleted ? { jobs: { scout: 'started', recommendations: 'started' } } : {}),
                }),
                '/api/projects/:id/signals/scout/configs/': () => [
                    { ...quickGeneralScout, enabled: quickActivationCompleted, emit: true },
                ],
                '/api/projects/:id/signals/source_configs/': () => ({
                    results: quickActivationCompleted
                        ? [
                              {
                                  id: 'source',
                                  source_product: 'error_tracking',
                                  source_type: 'issue_created',
                                  enabled: true,
                              },
                          ]
                        : [],
                    next: null,
                    count: quickActivationCompleted ? 1 : 0,
                }),
                '/api/projects/:id/integrations/': {
                    results: [
                        {
                            id: 1,
                            kind: 'github',
                            config: {},
                            display_name: 'example',
                            created_at: '2026-10-14',
                            icon_url: '',
                        },
                    ],
                    next: null,
                    count: 1,
                },
            },
            post: {
                '/api/projects/:id/signals/onboarding/expose/': { draft: null, completed_at: null },
                '/api/projects/:id/signals/scout/configs/sync/': [quickGeneralScout],
                '/api/projects/:id/signals/onboarding/': async ({ request }) => [
                    200,
                    { draft: await request.json(), completed_at: null },
                ],
                '/api/projects/:id/signals/config/': {},
                '/api/projects/:id/signals/source_configs/': async ({ request }) => [
                    201,
                    { ...((await request.json()) as object), id: 'source' },
                ],
                '/api/projects/:id/signals/scout/configs/': { ...quickGeneralScout, enabled: true, emit: true },
                '/api/projects/:id/signals/onboarding/complete/': async ({ request }) => {
                    quickActivationCompleted = true
                    return [
                        200,
                        {
                            draft: await request.json(),
                            completed_at: '2026-10-14T00:00:00Z',
                            jobs: { scout: 'started', recommendations: 'started' },
                        },
                    ]
                },
            },
            patch: { '/api/projects/:id/vision/scanners/:scanner/': {} },
        }),
    ],
}

export const QuickActivationFailed: Story = {
    ...QuickConnected,
    name: 'Quick activation error',
    render: () => {
        useStorybookMocks({
            post: {
                '/api/projects/:id/signals/onboarding/complete/': [
                    503,
                    { detail: 'Activation interrupted', code: 'activation_interrupted' },
                ],
            },
        })
        return <QuickActivationPreview />
    },
    beforeEach: () => {
        quickActivationCompleted = false
    },
    play: async ({ canvas, userEvent }) => {
        const activate = (await canvas.findByText('Activate Self-Driving')).closest('button')!
        await waitFor(() => expect(activate).toHaveAttribute('aria-disabled', 'false'))
        await userEvent.click(activate)
        const message = await canvas.findByText('Activation interrupted')
        await waitFor(() => {
            expect(inboxSetupLogic.values.saving).toBe(false)
            expect(message.parentElement!.clientWidth).toBeGreaterThan(0)
        })
        await expect(canvas.getByText('Retry')).toBeVisible()
    },
}

export const QuickActivated: Story = {
    render: () => (
        <div className="mx-auto max-w-4xl p-6">
            <InboxActivationPanel />
        </div>
    ),
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/suggestions/': mockScoutSuggestionSet({
                    generated_at: '2026-10-14T00:00:00Z',
                }),
                '/api/projects/:id/signals/onboarding/': {
                    draft,
                    completed_at: '2026-10-14T00:00:00Z',
                    jobs: { scout: 'started', recommendations: 'started' },
                },
                '/api/projects/:id/signals/scout/configs/': [{ ...quickGeneralScout, enabled: true, emit: true }],
                '/api/projects/:id/signals/source_configs/': {
                    results: [
                        { id: 'source', source_product: 'error_tracking', source_type: 'issue_created', enabled: true },
                    ],
                    next: null,
                    count: 1,
                },
            },
        }),
    ],
}
