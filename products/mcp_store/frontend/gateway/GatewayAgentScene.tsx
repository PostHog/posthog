import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowLeft, IconClock, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSwitch, LemonTable, LemonTag, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import type { ConnectionStateEnumApi, MCPGatewayServerApi } from '../generated/api.schemas'
import { ServerIcon } from '../scene/icons'
import { GatewayAgentLogicProps, gatewayAgentLogic } from './gatewayAgentLogic'
import { GatewayRouteGuard } from './GatewayRouteGuard'
import {
    AgentGrantScopeControl,
    DecisionTag,
    RemoveAllSharesButton,
    credentialOwnerLabel,
    sharedByOthersLabel,
} from './gatewayUtils'
import { AgentServerShare, agentServerAccessKey } from './mcpGatewayLogic'

export const scene: SceneExport<(typeof gatewayAgentLogic)['props']> = {
    component: GatewayAgentRouteScene,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

function GatewayAgentRouteScene({ id }: GatewayAgentLogicProps): JSX.Element {
    const logicProps: GatewayAgentLogicProps = { id }

    return (
        <GatewayRouteGuard requiresAdmin>
            <BindLogic logic={gatewayAgentLogic} props={logicProps}>
                <GatewayAgentScene {...logicProps} />
            </BindLogic>
        </GatewayRouteGuard>
    )
}

export function GatewayAgentScene({
    onBack,
    onOpenServer,
}: {
    id: GatewayAgentLogicProps['id']
    onBack?: () => void
    onOpenServer?: (serverId: string, scope: string) => void
}): JSX.Element {
    const {
        account,
        accountInitialized,
        accountLoading,
        accountStatusLoadingIds,
        agentServerAccessLoadingKeys,
        allServers,
        allServersLoading,
        currentUserId,
        recentCalls,
        recentCallsLoading,
        sharedServers,
        sharesByServerId,
        unsharedServers,
        visibleRecentCalls,
    } = useValues(gatewayAgentLogic)
    const { setAgentServerAccess, showMoreRecentCalls, toggleAccountStatus } = useActions(gatewayAgentLogic)

    if (!account && (!accountInitialized || accountLoading)) {
        return (
            <SceneContent>
                <BackToTeamButton onBack={onBack} />
                <div className="flex items-center justify-center gap-2 py-8 text-secondary">
                    <Spinner /> Loading agent…
                </div>
            </SceneContent>
        )
    }
    if (!account) {
        return (
            <SceneContent>
                <BackToTeamButton onBack={onBack} />
                <div className="py-8 text-center text-secondary">
                    Agent not found. Return to team & agents and choose another agent.
                </div>
            </SceneContent>
        )
    }

    const paused = account.status === 'paused'
    const statusLoading = accountStatusLoadingIds.has(account.id)

    const yourConnectionState = (serverId: string): ConnectionStateEnumApi | undefined =>
        account.servers.find(
            (accountServer) => accountServer.id === serverId && accountServer.shared_by.id === currentUserId
        )?.connection_state

    return (
        <SceneContent>
            <BackToTeamButton onBack={onBack} />

            <div className="flex items-start gap-3">
                <div className="flex items-center justify-center bg-surface-secondary rounded w-[52px] h-[52px]">
                    <IconSparkles className="text-2xl" />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <h1 className="mb-0 truncate">{account.name}</h1>
                        <LemonTag type={paused ? 'warning' : 'success'}>{paused ? 'Paused' : 'Active'}</LemonTag>
                    </div>
                    {account.description && <div className="text-secondary">{account.description}</div>}
                    <div className="flex items-center gap-1 text-xs text-secondary mt-1">
                        <IconClock />
                        {account.last_active_at ? (
                            <span>
                                Last call <TZLabel time={account.last_active_at} />
                            </span>
                        ) : (
                            <span>No calls yet</span>
                        )}
                    </div>
                </div>
                <LemonButton
                    type="tertiary"
                    loading={statusLoading}
                    onClick={() => {
                        if (!statusLoading) {
                            toggleAccountStatus(account.id, !paused)
                        }
                    }}
                >
                    {paused ? 'Resume agent' : 'Pause agent'}
                </LemonButton>
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Identity</h3>
                <div className="border rounded overflow-hidden">
                    <IdentityRow label="Authenticates as">
                        <span className="font-mono text-sm">{account.handle}</span>
                    </IdentityRow>
                    <IdentityRow label="Created">{dayjs(account.created_at).format('MMMM YYYY')}</IdentityRow>
                </div>
            </div>

            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                    <h3 className="mb-0">Shared servers</h3>
                    <LemonTag type="muted" size="small">
                        {sharedServers.length} of {allServers.length}
                    </LemonTag>
                </div>
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
                <div className="border rounded overflow-hidden divide-y">
                    {allServersLoading && allServers.length === 0 ? (
                        <div className="flex items-center justify-center gap-2 p-4 text-sm text-secondary">
                            <Spinner /> Loading shared servers…
                        </div>
                    ) : allServers.length === 0 ? (
                        <div className="p-4 text-sm text-secondary">
                            No servers are registered with the gateway yet. Add a server before sharing access.
                        </div>
                    ) : (
                        <>
                            {sharedServers.map((server) => (
                                <ServerAccessRow
                                    key={server.id}
                                    server={server}
                                    accountId={account.id}
                                    accountName={account.name}
                                    shared
                                    share={sharesByServerId[server.id]}
                                    connectionState={yourConnectionState(server.id)}
                                    loading={agentServerAccessLoadingKeys.has(
                                        agentServerAccessKey(account.id, server.id)
                                    )}
                                    onSetAccess={setAgentServerAccess}
                                    onOpenServer={onOpenServer}
                                />
                            ))}
                            {unsharedServers.length > 0 && (
                                <div className="bg-surface-secondary px-3 py-1.5 text-xs font-semibold text-secondary">
                                    Not shared
                                </div>
                            )}
                            {unsharedServers.map((server) => (
                                <ServerAccessRow
                                    key={server.id}
                                    server={server}
                                    accountId={account.id}
                                    accountName={account.name}
                                    shared={false}
                                    share={sharesByServerId[server.id]}
                                    loading={agentServerAccessLoadingKeys.has(
                                        agentServerAccessKey(account.id, server.id)
                                    )}
                                    onSetAccess={setAgentServerAccess}
                                    onOpenServer={onOpenServer}
                                />
                            ))}
                        </>
                    )}
                </div>
            </div>

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Recent tool calls</h3>
                <LemonTable
                    dataSource={visibleRecentCalls}
                    loading={recentCallsLoading}
                    emptyState="No tool calls from this agent yet. Tool calls will appear here after the agent uses a server."
                    columns={[
                        {
                            title: 'Time',
                            dataIndex: 'created_at',
                            render: (_, row) => <TZLabel time={row.created_at} />,
                        },
                        {
                            title: 'MCP server · tool called',
                            key: 'server',
                            render: (_, row) => (
                                <div className="min-w-0">
                                    <div className="flex items-baseline gap-2 min-w-0">
                                        <span className="font-semibold text-xs truncate">{row.server_name}</span>
                                        <span className="font-mono text-xs text-secondary truncate">
                                            {row.tool_name}()
                                        </span>
                                    </div>
                                    {row.credential_owner && (
                                        <div className="text-xs text-secondary">
                                            {credentialOwnerLabel(row.credential_owner, row.grant_scope)}
                                        </div>
                                    )}
                                </div>
                            ),
                        },
                        {
                            title: 'Decision',
                            dataIndex: 'decision',
                            render: (_, row) => <DecisionTag decision={row.decision} />,
                        },
                    ]}
                />
                {visibleRecentCalls.length < recentCalls.length && (
                    <div className="flex justify-center">
                        <LemonButton size="small" type="tertiary" onClick={showMoreRecentCalls}>
                            Show more
                        </LemonButton>
                    </div>
                )}
            </div>
        </SceneContent>
    )
}

function BackToTeamButton({ onBack }: { onBack?: () => void }): JSX.Element {
    return (
        <LemonButton
            type="tertiary"
            size="small"
            icon={<IconArrowLeft />}
            onClick={onBack ?? (() => router.actions.push(urls.mcpGatewayTab('team')))}
        >
            Back to team & agents
        </LemonButton>
    )
}

function IdentityRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="grid grid-cols-[10rem_1fr] items-center gap-3 border-b last:border-b-0 px-3 py-2">
            <span className="text-xs text-secondary">{label}</span>
            <span className="text-sm">{children}</span>
        </div>
    )
}

function ServerAccessRow({
    server,
    accountId,
    accountName,
    shared,
    share,
    connectionState,
    loading,
    onSetAccess,
    onOpenServer,
}: {
    server: MCPGatewayServerApi
    accountId: string
    accountName: string
    shared: boolean
    share?: AgentServerShare
    connectionState?: ConnectionStateEnumApi
    loading: boolean
    onSetAccess: (accountId: string, serverId: string, enabled: boolean) => void
    onOpenServer?: (serverId: string, scope: string) => void
}): JSX.Element {
    const sharedByYou = Boolean(share?.sharedByYou)
    const sharedByOthers = share?.sharedByOthers ?? []
    const attribution = share ? sharedByOthersLabel(share) : null
    const connectionDisabledReason = sharedByYou ? undefined : agentShareDisabledReason(server)
    const toolLabel = `${server.tool_count} ${server.tool_count === 1 ? 'tool' : 'tools'}`
    const connectionStatus = connectionState ? agentConnectionStatus(connectionState) : null

    return (
        <div className={`flex items-center gap-3 p-2 ${shared ? '' : 'bg-surface-secondary opacity-70'}`}>
            <ServerIcon iconDomain={server.icon_domain} serverUrl={server.url} size={28} />
            <div className="flex-1 min-w-0">
                <div className="font-semibold truncate">{server.name}</div>
                <div className="text-xs text-secondary truncate">
                    {sharedByYou ? `${toolLabel} available to this agent` : (attribution ?? toolLabel)}
                </div>
                {sharedByYou && connectionStatus && connectionState !== 'ready' && (
                    <div className="text-xs text-warning">{connectionStatus.detail}</div>
                )}
            </div>
            {sharedByYou && connectionStatus && (
                <LemonTag type={connectionState === 'ready' ? 'success' : 'warning'} size="small">
                    {connectionStatus.label}
                </LemonTag>
            )}
            {sharedByYou && share && (
                <AgentGrantScopeControl accountId={accountId} serverId={server.id} scope={share.yourScope} />
            )}
            {shared && (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    to={onOpenServer ? undefined : urls.mcpGatewayServer(server.id, `agent:${accountId}`)}
                    onClick={onOpenServer ? () => onOpenServer(server.id, `agent:${accountId}`) : undefined}
                >
                    Tool policies
                </LemonButton>
            )}
            {sharedByOthers.length > 0 && (
                <RemoveAllSharesButton
                    accountId={accountId}
                    accountName={accountName}
                    serverId={server.id}
                    serverName={server.name}
                    shareCount={sharedByOthers.length + (sharedByYou ? 1 : 0)}
                />
            )}
            <LemonSwitch
                checked={sharedByYou}
                loading={loading}
                disabledReason={connectionDisabledReason}
                aria-label={`${sharedByYou ? 'Stop sharing' : 'Share'} your ${server.name} connection with ${accountName}`}
                onChange={(checked) => {
                    if (!loading && (!checked || !connectionDisabledReason)) {
                        onSetAccess(accountId, server.id, checked)
                    }
                }}
            />
        </div>
    )
}

function agentShareDisabledReason(server: MCPGatewayServerApi): string | undefined {
    if (!server.is_team_enabled) {
        return 'Turn this server on for the team before sharing it with an agent.'
    }
    if (server.is_revoked_for_you) {
        return 'Ask an admin to restore your access before sharing this server.'
    }
    if (!server.your_connection) {
        return 'Connect this server before sharing it with an agent.'
    }
    if (server.your_connection.pending_oauth) {
        return 'Finish connecting this server before sharing it with an agent.'
    }
    if (server.your_connection.needs_reauth) {
        return 'Reconnect this server before sharing it with an agent.'
    }
    if (!server.your_connection.is_enabled) {
        return 'Turn your connection on before sharing this server with an agent.'
    }
    return undefined
}

function agentConnectionStatus(state: ConnectionStateEnumApi): { label: string; detail: string } {
    switch (state) {
        case 'ready':
            return { label: 'Ready', detail: '' }
        case 'pending_oauth':
            return { label: 'Finish connection', detail: 'Finish connecting your account to restore agent access.' }
        case 'needs_reauth':
            return { label: 'Reconnect', detail: 'Reconnect your account to restore agent access.' }
        case 'disabled':
            return { label: 'Connection off', detail: 'Turn your connection on to restore agent access.' }
        case 'missing_credential':
            return { label: 'Connect account', detail: 'Connect your account to restore agent access.' }
    }
}
