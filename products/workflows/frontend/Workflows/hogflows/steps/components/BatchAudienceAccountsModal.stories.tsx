import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import type { MockResolverInfo } from '~/mocks/utils'
import { AccountsQuery, NodeKind } from '~/queries/schema/schema-general'

import { BatchAudienceAccountsModal } from './BatchAudienceAccountsModal'

const AUDIENCE_QUERY: AccountsQuery = {
    kind: NodeKind.AccountsQuery,
    filterExpression: "isNotNull(accounts.external_id) AND accounts.external_id != ''",
}

// Assignee ids 178 and 202 match the default organization members mock.
const ACCOUNT_ROWS = [
    [
        {
            id: '0190a0a0-0000-7000-8000-000000000001',
            name: 'Acme',
            external_id: 'org-acme',
            logo_domain: 'acme.example',
        },
        ['enterprise', 'renewal'],
        3,
        [178],
    ],
    [
        {
            id: '0190a0a0-0000-7000-8000-000000000002',
            name: 'Globex',
            external_id: 'org-globex',
            logo_domain: 'globex.example',
        },
        ['enterprise'],
        0,
        [202],
    ],
    [
        { id: '0190a0a0-0000-7000-8000-000000000003', name: 'Initech', external_id: 'org-initech', logo_domain: null },
        [],
        1,
        [],
    ],
]

async function mockAccountsQuery({ request }: MockResolverInfo): Promise<[number, unknown] | undefined> {
    const body = (await request.clone().json()) as { query?: Record<string, any> }
    const query = body?.query
    if (query?.kind === NodeKind.DatabaseSchemaQuery) {
        return [200, { tables: {}, joins: [] }]
    }
    if (query?.kind !== NodeKind.AccountsQuery) {
        return [200, { results: [] }]
    }
    if (query.metrics && !query.select) {
        return [200, { kind: 'AccountsQuery', columns: [], results: [], types: [], metricsResults: [1], hogql: '' }]
    }
    return [
        200,
        {
            kind: 'AccountsQuery',
            columns: ['name', 'tag_names', 'notebook_count', 'csm'],
            results: ACCOUNT_ROWS,
            types: [],
            hogql: '',
            hasMore: false,
            limit: 100,
            offset: 0,
        },
    ]
}

function mockAccountIcon({ request }: MockResolverInfo): Response {
    const fill = new URL(request.url).searchParams.get('domain') === 'acme.example' ? '#8f68d4' : '#dc9300'
    return new Response(
        `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" rx="4" fill="${fill}"/></svg>`,
        { headers: { 'Content-Type': 'image/svg+xml' } }
    )
}

const meta: Meta<typeof BatchAudienceAccountsModal> = {
    title: 'Products/Workflows/Steps/Batch audience accounts',
    component: BatchAudienceAccountsModal,
    parameters: {
        mockDate: '2026-09-01',
        testOptions: { waitForSelector: '[data-attr="account-audience-search"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/account_relationship_definitions/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: '11111111-2222-3333-4444-555555555555',
                            name: 'CSM',
                            description: null,
                            is_single_holder: true,
                            is_controlled: false,
                        },
                    ],
                },
                'api/projects/:team_id/custom_property_definitions/': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
                'api/projects/:team_id/accounts/icon/': mockAccountIcon,
            },
            post: {
                '/api/environments/:team_id/query/': mockAccountsQuery,
                '/api/environments/:team_id/query/:query_kind/': mockAccountsQuery,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof BatchAudienceAccountsModal>

export const Default: Story = {
    args: {
        actionId: 'trigger',
        audienceQuery: AUDIENCE_QUERY,
        affected: 1839,
        isOpen: true,
        onClose: () => {},
    },
}
