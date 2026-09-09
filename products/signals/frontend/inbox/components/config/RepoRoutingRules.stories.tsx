import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { RepoRoutingRules } from './RepoRoutingRules'

// The routing rules block from the Code access settings section. It reads the team's rules
// (`tasks/repo_routing_rules`) and the connected GitHub integrations, so both GETs are mocked
// per story to place the block in a given state.

const GITHUB_INTEGRATION = {
    id: 1,
    kind: 'github',
    display_name: 'PostHog',
    config: {},
    created_at: '2024-01-01T00:00:00Z',
    errors: '',
}

const CREATOR = {
    id: 1,
    uuid: '018f0000-0000-7000-8000-0000000000aa',
    email: 'max@posthog.com',
    first_name: 'Max',
    hedgehog_config: null,
}

const RULES = [
    {
        id: '018f0000-0000-7000-8000-000000000001',
        rule_text: 'anything about the marketing site or docs',
        repository: 'posthog/posthog.com',
        priority: 0,
        created_by: CREATOR,
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
    },
    {
        id: '018f0000-0000-7000-8000-000000000002',
        rule_text: 'crashes in the Android app',
        repository: 'posthog/posthog-android',
        priority: 1,
        created_by: null,
        created_at: '2024-01-02T00:00:00Z',
        updated_at: '2024-01-02T00:00:00Z',
    },
]

function Block({ rules = RULES, withGithub = true }: { rules?: typeof RULES; withGithub?: boolean }): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:team_id/tasks/repo_routing_rules/': rules,
            '/api/environments/:team_id/integrations/': { results: withGithub ? [GITHUB_INTEGRATION] : [] },
            '/api/environments/:team_id/integrations/:id/github_repos/': {
                repositories: [
                    { id: 1, name: 'posthog.com', full_name: 'posthog/posthog.com' },
                    { id: 2, name: 'posthog-android', full_name: 'posthog/posthog-android' },
                ],
                has_more: false,
                total: 2,
            },
        },
    })
    // Mimic the Settings tab card width so wrapping matches the scene.
    return (
        <div className="w-[40rem] max-w-full rounded border border-primary bg-surface-primary p-4">
            <RepoRoutingRules />
        </div>
    )
}

const meta: Meta = {
    title: 'Scenes-App/Inbox/RepoRoutingRules',
    component: RepoRoutingRules,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
        mockDate: '2024-03-20',
    },
}
export default meta

type Story = StoryObj

export const WithRules: Story = {
    render: () => <Block />,
}

export const NoRules: Story = {
    render: () => <Block rules={[]} />,
}

// Without a GitHub connection the add row gives way to a pointer at the connect card above.
export const NoGithubConnection: Story = {
    render: () => <Block rules={[]} withGithub={false} />,
}

// More than one page of rules: the pager appears under the rows, ten per page.
export const ManyRules: Story = {
    render: () => (
        <Block
            rules={Array.from({ length: 14 }, (_, i) => ({
                id: `018f0000-0000-7000-8000-0000000000${String(i).padStart(2, '0')}`,
                rule_text: `rule ${i + 1}`,
                repository: i % 2 === 0 ? 'posthog/posthog.com' : 'posthog/posthog-android',
                priority: i,
                created_by: i % 2 === 0 ? CREATOR : null,
                created_at: '2024-01-01T00:00:00Z',
                updated_at: '2024-01-01T00:00:00Z',
            }))}
        />
    ),
}
