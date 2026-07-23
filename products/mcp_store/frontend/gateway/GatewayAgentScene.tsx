import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSwitch, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ServerIcon } from '../scene/icons'
import { gatewayAgentLogic } from './gatewayAgentLogic'
import { DecisionTag } from './gatewayUtils'
import { agentServerAccessKey } from './mcpGatewayLogic'

export const scene: SceneExport<(typeof gatewayAgentLogic)['props']> = {
    component: GatewayAgentScene,
    logic: gatewayAgentLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function GatewayAgentScene(): JSX.Element {
    const {
        account,
        accountLoading,
        accountStatusLoadingIds,
        agentServerAccessLoadingKeys,
        allServers,
        sharedServerIds,
        recentCalls,
    } = useValues(gatewayAgentLogic)
    const { setAgentServerAccess, toggleAccountStatus } = useActions(gatewayAgentLogic)

    if (!account && accountLoading) {
        return <SceneContent>Loading…</SceneContent>
    }
    if (!account) {
        return <SceneContent>Agent not found.</SceneContent>
    }

    const paused = account.status === 'paused'

    return (
        <SceneContent>
            <LemonButton size="small" onClick={() => router.actions.push(urls.mcpGatewayTab('team'))}>
                ‹ Back to team & agents
            </LemonButton>

            <div className="flex items-center gap-3">
                <div className="flex items-center justify-center bg-surface-secondary rounded w-[52px] h-[52px]">
                    <IconSparkles className="text-2xl" />
                </div>
                <div className="flex-1">
                    <div className="flex items-center gap-2">
                        <h1 className="mb-0">{account.name}</h1>
                        <LemonTag type={account.product_enabled ? 'success' : 'muted'}>
                            {account.product_enabled ? 'Product available' : 'Product unavailable'}
                        </LemonTag>
                        <LemonTag type={paused ? 'warning' : 'success'}>
                            {paused ? 'MCP paused' : 'MCP enabled'}
                        </LemonTag>
                    </div>
                    <div className="text-secondary">{account.description}</div>
                </div>
                <LemonButton
                    type="secondary"
                    loading={accountStatusLoadingIds.has(account.id)}
                    disabledReason={
                        paused && !account.product_enabled
                            ? account.product_disabled_reason ||
                              'Enable this agent’s PostHog product before resuming it.'
                            : undefined
                    }
                    onClick={() => toggleAccountStatus(account.id, !paused)}
                >
                    {paused ? 'Resume agent' : 'Pause agent'}
                </LemonButton>
            </div>

            <LemonDivider />

            {!account.product_enabled && (
                <LemonBanner type="info">
                    {account.product_disabled_reason || 'Enable this agent’s PostHog product before resuming it.'} MCP
                    access settings stay saved while the agent is unavailable.
                </LemonBanner>
            )}

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">
                    Shared servers · {sharedServerIds.size} of {allServers.length}
                </h3>
                <div className="border rounded divide-y">
                    {allServers.map((server) => {
                        const shared = sharedServerIds.has(server.id)
                        const needsConnection =
                            !shared && server.your_connection === null && server.shared_credential === null
                        return (
                            <div key={server.id} className="flex items-center gap-3 p-2">
                                <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={28} />
                                <div className="flex-1 min-w-0">
                                    <div className="font-semibold">{server.name}</div>
                                    <div className="text-xs text-secondary">
                                        {shared ? `${server.tool_count} tools` : 'Not shared'}
                                    </div>
                                </div>
                                {shared && (
                                    <LemonButton
                                        size="xsmall"
                                        type="secondary"
                                        to={urls.mcpGatewayServer(server.id, `agent:${account.id}`)}
                                    >
                                        Tool policies
                                    </LemonButton>
                                )}
                                <LemonSwitch
                                    checked={shared}
                                    loading={agentServerAccessLoadingKeys.has(
                                        agentServerAccessKey(account.id, server.id)
                                    )}
                                    disabledReason={
                                        needsConnection
                                            ? 'Connect this server before sharing it with an agent.'
                                            : undefined
                                    }
                                    aria-label={`${shared ? 'Revoke' : 'Grant'} ${account.name} access to ${server.name}`}
                                    onChange={(checked) => setAgentServerAccess(account.id, server.id, checked)}
                                />
                            </div>
                        )
                    })}
                </div>
            </div>

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Recent tool calls</h3>
                <LemonTable
                    dataSource={recentCalls}
                    emptyState="No tool calls from this agent yet."
                    columns={[
                        {
                            title: 'Time',
                            dataIndex: 'created_at',
                            render: (_, row) => <TZLabel time={row.created_at} />,
                        },
                        { title: 'MCP server', dataIndex: 'server_name' },
                        {
                            title: 'Tool',
                            dataIndex: 'tool_name',
                            render: (_, row) => <span className="font-mono text-xs">{row.tool_name}()</span>,
                        },
                        {
                            title: 'Decision',
                            dataIndex: 'decision',
                            render: (_, row) => <DecisionTag decision={row.decision} />,
                        },
                    ]}
                />
            </div>
        </SceneContent>
    )
}
