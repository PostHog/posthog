import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { MCPServiceAccountServerApi } from 'products/mcp_store/frontend/generated/api.schemas'

import { ScoutMcpServersPicker } from './ScoutMcpServersPicker'

function server(id: string, name: string): MCPServiceAccountServerApi {
    return {
        id,
        shared_by: {
            id: MOCK_DEFAULT_USER.id,
            uuid: MOCK_DEFAULT_USER.uuid,
            email: MOCK_DEFAULT_USER.email,
            hedgehog_config: null,
        },
        scope: 'team',
        name,
        description: `${name} workspace`,
        url: `https://mcp.${name.toLowerCase()}.example.com/mcp`,
        icon_key: name.toLowerCase(),
        icon_domain: `${name.toLowerCase()}.com`,
        connection_state: 'ready',
        reachable: true,
    }
}

const SERVERS = [
    server('linear-id', 'Linear'),
    server('notion-id', 'Notion'),
    server('github-id', 'GitHub'),
    server('stripe-id', 'Stripe'),
]

describe('ScoutMcpServersPicker', () => {
    beforeEach(() => {
        // featureFlagLogic persists to localStorage, which jsdom keeps across tests.
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.MCP_GATEWAY], { [FEATURE_FLAGS.MCP_GATEWAY]: true })
        // msw handlers reset between tests, so register per test rather than once per file.
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () => [
                    200,
                    {
                        count: 1,
                        next: null,
                        previous: null,
                        results: [
                            {
                                id: 'scout-id',
                                name: 'scout',
                                description: 'Scheduled scouts',
                                handle: 'svc-scout',
                                agent_key: 'scout',
                                status: 'active',
                                server_ids: SERVERS.map(({ id }) => id),
                                servers: SERVERS,
                                last_active_at: null,
                                created_at: '2026-07-22T00:00:00Z',
                                updated_at: '2026-07-22T00:00:00Z',
                            },
                        ],
                    },
                ],
            },
        })
    })
    afterEach(cleanup)

    // The header is all most people read, so a scout with servers must not read "None". The names
    // come from the team's shares, so a selection whose share was withdrawn drops out of the header
    // the same way it drops out of what the run mounts.
    it.each([
        ['the servers it may use', ['linear-id'], ['Linear'], ['None', 'Notion']],
        ['nothing selected', [], ['None'], ['Linear']],
        ['a selection the team no longer shares', ['retired-id'], ['None'], []],
        // A scout may hold up to 100 servers. An unbounded header would push the row it
        // summarizes, and everything under it, off the screen.
        [
            'more servers than the header shows',
            ['linear-id', 'notion-id', 'github-id', 'stripe-id'],
            ['GitHub', 'Linear', 'Notion', '+1 more'],
            ['Stripe'],
        ],
    ])(
        'summarizes %s in the header, with the section closed',
        async (_name, selectedServerIds: string[], expected: string[], unexpected: string[]) => {
            render(<ScoutMcpServersPicker compact selectedServerIds={selectedServerIds} onChange={jest.fn()} />)

            for (const text of expected) {
                expect(await screen.findByText(text)).toBeInTheDocument()
            }
            for (const text of unexpected) {
                expect(screen.queryByText(text)).not.toBeInTheDocument()
            }
        }
    )

    // A scout keeps mounting every server it holds when the lookup fails, so a header that read
    // "None" would report access the scout still has as removed.
    it('says nothing about servers when the lookup fails', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/mcp_gateway/service_accounts/': () => [500, { detail: 'nope' }],
            },
        })

        render(<ScoutMcpServersPicker compact selectedServerIds={['linear-id']} onChange={jest.fn()} />)

        expect(await screen.findByText('MCP servers')).toBeInTheDocument()
        expect(screen.queryByText('None')).not.toBeInTheDocument()
        expect(screen.queryByText('Linear')).not.toBeInTheDocument()
    })

    // The selection must be settable before the scout is enabled, or the first run of a newly
    // enabled scout races out with the wrong toolset. The form passes no disabled reason for that,
    // so the switches inside the panel stay live.
    it('opens to switches that are still editable', async () => {
        const onChange = jest.fn()
        render(<ScoutMcpServersPicker compact selectedServerIds={[]} onChange={onChange} />)

        fireEvent.click(await screen.findByText('MCP servers'))

        const linearSwitch = await screen.findByLabelText('Let this scout use Linear')
        expect(linearSwitch).not.toBeDisabled()

        fireEvent.click(linearSwitch)
        expect(onChange).toHaveBeenCalledWith(['linear-id'])
    })
})
