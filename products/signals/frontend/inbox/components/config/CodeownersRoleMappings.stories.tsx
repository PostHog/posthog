import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import type { RoleExternalReferenceApi } from 'products/integrations/frontend/generated/api.schemas'

import { CodeownersRoleMappings } from './CodeownersRoleMappings'

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
    distinct_id: 'max-distinct-id',
    email: 'max@posthog.com',
    first_name: 'Max',
    hedgehog_config: null,
}

const ROLES = [
    {
        id: '018f0000-0000-7000-8000-000000000101',
        name: 'Dev Ex',
        members: [],
        created_at: '2024-01-01T00:00:00Z',
        created_by: CREATOR,
        is_default: false,
    },
    {
        id: '018f0000-0000-7000-8000-000000000102',
        name: 'Error Tracking',
        members: [],
        created_at: '2024-01-01T00:00:00Z',
        created_by: CREATOR,
        is_default: false,
    },
    {
        id: '018f0000-0000-7000-8000-000000000103',
        name: 'Security',
        members: [],
        created_at: '2024-01-01T00:00:00Z',
        created_by: CREATOR,
        is_default: false,
    },
    {
        id: '018f0000-0000-7000-8000-000000000104',
        name: 'Legacy Infra',
        members: [],
        created_at: '2024-01-01T00:00:00Z',
        created_by: CREATOR,
        is_default: false,
    },
]

const REFERENCES: RoleExternalReferenceApi[] = [
    {
        id: '018f0000-0000-7000-8000-000000000201',
        provider: 'github',
        provider_organization_id: 'posthog',
        provider_role_id: '1001',
        provider_role_slug: 'team-cymbal',
        provider_role_name: 'Error Tracking',
        role: '018f0000-0000-7000-8000-000000000102',
        sync_mode: 'auto',
        role_created_by_sync: true,
        orphaned_at: null,
        last_synced_at: '2024-03-20T10:00:00Z',
        drift: {
            has_drift: false,
            to_add_count: 0,
            to_remove_count: 0,
            provider_member_count: 4,
            matched_posthog_member_count: 4,
            current_role_member_count: 4,
        },
        created_at: '2024-01-01T00:00:00Z',
        created_by: CREATOR,
    },
    {
        id: '018f0000-0000-7000-8000-000000000202',
        provider: 'github',
        provider_organization_id: 'posthog',
        provider_role_id: '1002',
        provider_role_slug: 'team-security',
        provider_role_name: 'Team Security',
        role: '018f0000-0000-7000-8000-000000000103',
        sync_mode: 'proposed',
        role_created_by_sync: false,
        orphaned_at: null,
        last_synced_at: '2024-03-20T10:00:00Z',
        drift: {
            has_drift: true,
            to_add_count: 2,
            to_remove_count: 0,
            provider_member_count: 5,
            matched_posthog_member_count: 4,
            current_role_member_count: 2,
        },
        created_at: '2024-01-01T00:00:00Z',
        created_by: CREATOR,
    },
    {
        id: '018f0000-0000-7000-8000-000000000203',
        provider: 'github',
        provider_organization_id: 'posthog',
        provider_role_id: '1003',
        provider_role_slug: 'team-legacy-infra',
        provider_role_name: 'Legacy Infra',
        role: '018f0000-0000-7000-8000-000000000104',
        sync_mode: 'auto',
        role_created_by_sync: true,
        orphaned_at: '2024-03-19T15:00:00Z',
        last_synced_at: '2024-03-18T10:00:00Z',
        drift: {
            has_drift: false,
            to_add_count: 0,
            to_remove_count: 0,
            provider_member_count: 2,
            matched_posthog_member_count: 2,
            current_role_member_count: 2,
        },
        created_at: '2024-01-01T00:00:00Z',
        created_by: CREATOR,
    },
]

const SCANNED_TEAMS = [
    {
        provider_organization_id: 'posthog',
        team_slug: 'team-cymbal',
        handle: '@posthog/team-cymbal',
        repositories: ['PostHog/posthog'],
        likely_role_id: '018f0000-0000-7000-8000-000000000102',
        likely_role_name: 'Error Tracking',
        match_source: 'external_reference',
    },
    {
        provider_organization_id: 'posthog',
        team_slug: 'team-devex',
        handle: '@posthog/team-devex',
        repositories: ['PostHog/posthog'],
        likely_role_id: '018f0000-0000-7000-8000-000000000101',
        likely_role_name: 'Dev Ex',
        match_source: 'name_match',
    },
    {
        provider_organization_id: 'posthog',
        team_slug: 'unmapped-squad',
        handle: '@posthog/unmapped-squad',
        repositories: ['PostHog/posthog'],
        likely_role_id: null,
        likely_role_name: null,
        match_source: null,
    },
]

function Block({
    roles = ROLES,
    references = REFERENCES,
    teams = SCANNED_TEAMS,
    failReferences = false,
}: {
    roles?: typeof ROLES
    references?: typeof REFERENCES
    teams?: typeof SCANNED_TEAMS
    failReferences?: boolean
}): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/organizations/:organization_id/roles/': { count: roles.length, results: roles },
            '/api/organizations/:organization_id/role_external_references/': failReferences
                ? [500, { detail: 'Server error' }]
                : { count: references.length, results: references },
            '/api/projects/:team_id/signals/codeowners_teams/': {
                teams,
                scanned_repository_count: teams.length > 0 ? 1 : 0,
                total_repository_count: teams.length > 0 ? 1 : 0,
            },
            '/api/projects/:team_id/integrations/': { results: [GITHUB_INTEGRATION] },
        },
    })
    return (
        <div className="w-[44rem] max-w-full rounded border border-primary bg-surface-primary p-4">
            <CodeownersRoleMappings />
        </div>
    )
}

const meta: Meta = {
    title: 'Scenes-App/Inbox/CodeownersRoleMappings',
    component: CodeownersRoleMappings,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
        mockDate: '2024-03-20',
    },
}
export default meta

type Story = StoryObj

export const MappedAndSuggested: Story = {
    render: () => <Block />,
}

export const EmptyTeams: Story = {
    render: () => <Block references={[]} teams={[]} />,
}

export const NoOrganizationRoles: Story = {
    render: () => (
        <Block
            roles={[]}
            references={[]}
            teams={SCANNED_TEAMS.map((team) => ({
                ...team,
                likely_role_id: null,
                likely_role_name: null,
                match_source: null,
            }))}
        />
    ),
}

export const LoadError: Story = {
    // The rejected loader raises a global error toast, which the snapshot runner treats as an active loader.
    parameters: { testOptions: { snapshotBrowsers: [] } },
    render: () => <Block failReferences />,
}
