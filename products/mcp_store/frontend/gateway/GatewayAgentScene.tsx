import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSwitch, LemonTable, LemonTag, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { ServerIcon } from '../scene/icons'
import { gatewayAgentLogic } from './gatewayAgentLogic'
import {
    AgentGrantScopeControl,
    DecisionTag,
    RemoveAllSharesButton,
    credentialOwnerLabel,
    sharedByOthersLabel,
} from './gatewayUtils'
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
        allServersLoading,
        sharedServerIds,
        sharesByServerId,
        recentCalls,
        recentCallsLoading,
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
                        <LemonTag type={paused ? 'warning' : 'success'}>
                            {paused ? 'MCP paused' : 'MCP enabled'}
                        </LemonTag>
                    </div>
                    <div className="text-secondary">{account.description}</div>
                </div>
                <LemonButton
                    type="secondary"
                    loading={accountStatusLoadingIds.has(account.id)}
                    onClick={() => toggleAccountStatus(account.id, !paused)}
                >
                    {paused ? 'Resume agent' : 'Pause agent'}
                </LemonButton>
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">
                    Shared servers{!allServersLoading && ` · ${sharedServerIds.size} of ${allServers.length}`}
                </h3>
                <div className="text-sm text-secondary">
                    You share your own connections. A personal share lets {account.name} use one when it runs for you. A
                    team share lets it use one for every {account.name} run in this project, including runs nobody
                    started. Teammates can't use the connection directly, but a team share means agents act through it
                    on their runs too.
                </div>
                {account.agent_key === 'support' && (
                    <div className="text-sm text-secondary">
                        Support replies often run without a person behind them. A personal share goes unused on those
                        runs. A team share covers them.
                    </div>
                )}
                <div className="border rounded divide-y">
                    {allServersLoading && allServers.length === 0 ? (
                        <div className="flex items-center gap-2 p-3 text-sm text-secondary">
                            <Spinner /> Loading shared servers…
                        </div>
                    ) : (
                        allServers.map((server) => {
                            const share = sharesByServerId[server.id]
                            const sharedByYou = Boolean(share?.sharedByYou)
                            const sharedByOthers = share?.sharedByOthers ?? []
                            const attribution = share ? sharedByOthersLabel(share) : null
                            const shared = sharedServerIds.has(server.id)
                            const needsConnection = !sharedByYou && server.your_connection === null
                            return (
                                <div key={server.id} className="flex items-center gap-3 p-2">
                                    <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={28} />
                                    <div className="flex-1 min-w-0">
                                        <div className="font-semibold">{server.name}</div>
                                        <div className="text-xs text-secondary truncate">
                                            {sharedByYou ? `${server.tool_count} tools` : (attribution ?? 'Not shared')}
                                        </div>
                                    </div>
                                    {sharedByYou && (
                                        <AgentGrantScopeControl
                                            accountId={account.id}
                                            serverId={server.id}
                                            scope={share.yourScope}
                                        />
                                    )}
                                    {shared && (
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            to={urls.mcpGatewayServer(server.id, `agent:${account.id}`)}
                                        >
                                            Tool policies
                                        </LemonButton>
                                    )}
                                    {sharedByOthers.length > 0 && (
                                        <RemoveAllSharesButton
                                            accountId={account.id}
                                            accountName={account.name}
                                            serverId={server.id}
                                            serverName={server.name}
                                            shareCount={sharedByOthers.length + (sharedByYou ? 1 : 0)}
                                        />
                                    )}
                                    <LemonSwitch
                                        checked={sharedByYou}
                                        loading={agentServerAccessLoadingKeys.has(
                                            agentServerAccessKey(account.id, server.id)
                                        )}
                                        disabledReason={
                                            needsConnection
                                                ? 'Connect this server before sharing it with an agent.'
                                                : undefined
                                        }
                                        aria-label={`${sharedByYou ? 'Stop sharing' : 'Share'} your ${server.name} connection with ${account.name}`}
                                        onChange={(checked) => setAgentServerAccess(account.id, server.id, checked)}
                                    />
                                </div>
                            )
                        })
                    )}
                </div>
            </div>

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Recent tool calls</h3>
                <LemonTable
                    dataSource={recentCalls}
                    loading={recentCallsLoading}
                    emptyState="No tool calls from this agent yet."
                    columns={[
                        {
                            title: 'Time',
                            dataIndex: 'created_at',
                            render: (_, row) => <TZLabel time={row.created_at} />,
                        },
                        {
                            title: 'MCP server',
                            key: 'server',
                            render: (_, row) => (
                                <div>
                                    <div>{row.server_name}</div>
                                    {row.credential_owner && (
                                        <div className="text-xs text-secondary">
                                            {credentialOwnerLabel(row.credential_owner, row.grant_scope)}
                                        </div>
                                    )}
                                </div>
                            ),
                        },
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
