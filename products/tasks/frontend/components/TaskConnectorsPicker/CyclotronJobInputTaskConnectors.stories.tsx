import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type {
    MCPServiceAccountApi,
    MCPServiceAccountServerApi,
} from 'products/mcp_store/frontend/generated/api.schemas'

import CyclotronJobInputTaskConnectors from './CyclotronJobInputTaskConnectors'

// The "Connectors" input of a workflow's "Create AI task" step: one switch per MCP server shared
// with everyone in the project.

const SHARED_BY = { id: 2, uuid: 'teammate-uuid', email: 'teammate@posthog.com', hedgehog_config: null }

function server(
    id: string,
    name: string,
    connectionState: MCPServiceAccountServerApi['connection_state'] = 'ready'
): MCPServiceAccountServerApi {
    return {
        id,
        shared_by: SHARED_BY,
        scope: 'team',
        name,
        description: `${name} workspace`,
        // Empty keeps the icon fallback deterministic in stories: no logo request, no onError race.
        url: '',
        icon_key: '',
        icon_domain: '',
        connection_state: connectionState,
        reachable: true,
    }
}

function workflowAccount(servers: MCPServiceAccountServerApi[]): MCPServiceAccountApi {
    return {
        id: 'workflow-id',
        name: 'Workflow agent',
        description: 'Runs the AI tasks that workflows start.',
        handle: 'posthog-workflow',
        agent_key: 'workflow',
        status: 'active',
        server_ids: servers.map(({ id }) => id),
        servers,
        last_active_at: null,
        created_at: '2026-08-28T00:00:00Z',
        updated_at: '2026-08-28T00:00:00Z',
    }
}

const SERVERS = [
    server('incident-id', 'Incident.io'),
    server('datadog-id', 'Datadog', 'needs_reauth'),
    server('linear-id', 'Linear'),
]

function Picker({ initialValue }: { initialValue: string[] }): JSX.Element {
    const [value, setValue] = useState<string[]>(initialValue)
    return (
        <div className="w-[420px] p-2">
            <CyclotronJobInputTaskConnectors
                schema={{ key: 'connectors', type: 'task_mcp_installations', label: 'Connectors' }}
                value={value}
                onChange={setValue}
            />
        </div>
    )
}

const meta: Meta<typeof CyclotronJobInputTaskConnectors> = {
    title: 'Scenes-App/Workflows/CreateAiTaskConnectors',
    component: CyclotronJobInputTaskConnectors,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () => [
                    200,
                    { count: 1, next: null, previous: null, results: [workflowAccount(SERVERS)] },
                ],
            },
        }),
    ],
    parameters: {
        featureFlags: { [FEATURE_FLAGS.MCP_GATEWAY]: true },
        testOptions: { waitForLoadersToDisappear: true },
    },
}
export default meta

type Story = StoryObj<typeof CyclotronJobInputTaskConnectors>

export const Selection: Story = {
    render: () => <Picker initialValue={['incident-id']} />,
}

// A saved id that no team share backs anymore keeps a row, so it can be switched off.
export const UnavailableConnector: Story = {
    render: () => <Picker initialValue={['incident-id', 'gone-id']} />,
}

export const NothingShared: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () => [
                    200,
                    { count: 1, next: null, previous: null, results: [workflowAccount([])] },
                ],
            },
        }),
    ],
    render: () => <Picker initialValue={[]} />,
}
