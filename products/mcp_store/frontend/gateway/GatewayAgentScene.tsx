import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCopy, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSwitch, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ServerIcon } from '../scene/icons'
import { gatewayAgentLogic } from './gatewayAgentLogic'
import { DecisionTag } from './gatewayUtils'

export const scene: SceneExport<(typeof gatewayAgentLogic)['props']> = {
    component: GatewayAgentScene,
    logic: gatewayAgentLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function GatewayAgentScene(): JSX.Element {
    const { account, accountLoading, allServers, sharedServerIds, recentCalls } = useValues(gatewayAgentLogic)
    const { setServerAccess, toggleAccountStatus, deleteServiceAccount, rotateServiceAccountToken } =
        useActions(gatewayAgentLogic)

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
                        {paused ? (
                            <LemonTag type="warning">Paused</LemonTag>
                        ) : (
                            <LemonTag type="success">Active</LemonTag>
                        )}
                    </div>
                    <div className="text-secondary">{account.description}</div>
                </div>
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={() => toggleAccountStatus(account.id, !paused)}
                    >
                        {paused ? 'Resume agent' : 'Pause agent'}
                    </LemonButton>
                    <LemonButton
                        status="danger"
                        type="secondary"
                        onClick={() => deleteServiceAccount(account.id)}
                    >
                        Delete
                    </LemonButton>
                </div>
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Identity</h3>
                <div className="border rounded p-3 flex flex-col gap-2">
                    <div className="flex items-center gap-2">
                        <span className="text-sm text-secondary w-40">Authenticates as</span>
                        <span className="font-mono text-sm">{account.handle}</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="text-sm text-secondary w-40">Gateway token</span>
                        <span className="font-mono text-sm">{account.token_mask || 'mcp_gw_ ••••'}</span>
                        <LemonButton
                            size="xsmall"
                            icon={<IconCopy />}
                            tooltip="The token is only shown in full when created or rotated"
                            onClick={() => void copyToClipboard(account.token_mask, 'masked token')}
                        />
                        <LemonButton size="xsmall" type="secondary" onClick={() => rotateServiceAccountToken(account.id)}>
                            Rotate…
                        </LemonButton>
                    </div>
                </div>
            </div>

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">
                    Shared servers · {sharedServerIds.size} of {allServers.length}
                </h3>
                <div className="border rounded divide-y">
                    {allServers.map((server) => {
                        const shared = sharedServerIds.has(server.id)
                        return (
                            <div key={server.id} className="flex items-center gap-3 p-2">
                                <ServerIcon iconKey={server.icon_key || undefined} size={28} />
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
                                    onChange={(checked) => setServerAccess(server.id, checked)}
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
