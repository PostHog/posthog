import { useActions, useValues } from 'kea'

import { IconClock, IconSparkles } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Heading,
    ItemGroup,
    Separator,
    Skeleton,
    Text,
    DataTableProps,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import type { MCPAuditEventApi } from '../generated/api.schemas'
import { GatewayAgentLogicProps, gatewayAgentLogic } from './gatewayAgentLogic'
import { yourAgentConnectionState } from './GatewayAgentScene'
import { credentialOwnerLabel } from './gatewayUtils'
import { agentServerAccessKey } from './mcpGatewayLogic'
import { QuillDecisionTag } from './QuillDecisionTag'
import { QuillGatewayAgentServerRow } from './QuillGatewayAgentServerRow'
import { QuillGatewayBackToTeamButton } from './QuillGatewayBackToTeamButton'

const RECENT_CALL_COLUMNS: DataTableProps<MCPAuditEventApi, unknown>['columns'] = [
    {
        id: 'created_at',
        header: 'Time',
        cell: ({ row }) => <TZLabel time={row.original.created_at} />,
    },
    {
        id: 'server',
        header: 'MCP server · tool called',
        meta: { expand: true },
        cell: ({ row }) => (
            <div className="flex min-w-0 flex-col">
                <div className="flex min-w-0 items-baseline gap-2">
                    <Text size="xs" weight="semibold" className="m-0 truncate" render={<span />}>
                        {row.original.server_name}
                    </Text>
                    <Text size="xs" variant="muted" className="m-0 truncate font-mono" render={<span />}>
                        {`${row.original.tool_name}()`}
                    </Text>
                </div>
                {row.original.credential_owner && (
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        {credentialOwnerLabel(row.original.credential_owner, row.original.grant_scope)}
                    </Text>
                )}
            </div>
        ),
    },
    {
        id: 'decision',
        header: 'Decision',
        cell: ({ row }) => <QuillDecisionTag decision={row.original.decision} />,
    },
]

export function QuillGatewayAgentScene({
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
            <div className="flex flex-col gap-4" role="status" aria-label="Loading agent…" aria-busy>
                <QuillGatewayBackToTeamButton onBack={onBack} />
                <Skeleton className="h-14" />
                <Skeleton className="h-32" />
            </div>
        )
    }

    if (!account) {
        return (
            <div className="flex flex-col gap-4">
                <QuillGatewayBackToTeamButton onBack={onBack} />
                <Empty>
                    <EmptyHeader>
                        <EmptyDescription>
                            Agent not found. Return to team & agents and choose another agent.
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            </div>
        )
    }

    const paused = account.status === 'paused'
    const statusLoading = accountStatusLoadingIds.has(account.id)

    return (
        <div className="flex min-w-0 flex-col gap-4">
            <QuillGatewayBackToTeamButton onBack={onBack} />

            <div className="flex flex-wrap items-start gap-3">
                <span data-quill className="flex size-13 shrink-0 items-center justify-center rounded-md bg-muted">
                    <IconSparkles className="text-2xl" />
                </span>
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <Heading size="base" render={<h3 className="m-0 truncate" />}>
                            {account.name}
                        </Heading>
                        <Badge variant={paused ? 'warning' : 'success'}>{paused ? 'Paused' : 'Active'}</Badge>
                    </div>
                    {account.description && (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {account.description}
                        </Text>
                    )}
                    <Text
                        size="xs"
                        variant="muted"
                        className="flex items-center gap-1"
                        render={<span className="m-0" />}
                    >
                        <IconClock />
                        {account.last_active_at ? (
                            <span>
                                Last call <TZLabel time={account.last_active_at} />
                            </span>
                        ) : (
                            <span>No calls yet</span>
                        )}
                    </Text>
                </div>
                <Button
                    variant="default"
                    loading={statusLoading}
                    onClick={() => {
                        if (!statusLoading) {
                            toggleAccountStatus(account.id, !paused)
                        }
                    }}
                >
                    {paused ? 'Resume agent' : 'Pause agent'}
                </Button>
            </div>

            <Separator />

            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Identity
                </Heading>
                <div className="flex flex-col divide-y divide-border rounded-md border border-border">
                    <div className="flex flex-wrap items-center gap-3 px-3 py-2">
                        <Text size="xs" variant="muted" className="w-40 shrink-0" render={<span className="m-0" />}>
                            Authenticates as
                        </Text>
                        <Text size="xs" className="font-mono" render={<span className="m-0" />}>
                            {account.handle}
                        </Text>
                    </div>
                    <div className="flex flex-wrap items-center gap-3 px-3 py-2">
                        <Text size="xs" variant="muted" className="w-40 shrink-0" render={<span className="m-0" />}>
                            Created
                        </Text>
                        <Text size="xs" render={<span className="m-0" />}>
                            {dayjs(account.created_at).format('MMMM YYYY')}
                        </Text>
                    </div>
                </div>
            </div>

            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Shared servers
                    </Heading>
                    <Badge>{`${sharedServers.length} of ${allServers.length}`}</Badge>
                </div>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    {`You share your own connections. A personal share lets ${account.name} use one when it runs for you. A team share lets it use one for every ${account.name} run in this project, including runs nobody started. Teammates can't use the connection directly, but a team share means agents act through it on their runs too.`}
                </Text>
                {account.agent_key === 'support' && (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Support replies often run without a person behind them. A personal share goes unused on those
                        runs. A team share covers them.
                    </Text>
                )}
                {account.agent_key === 'workflow' && (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Workflow tasks always run without a person behind them, so only team shares are available to
                        them. A workflow's "Create AI task" step picks among those.
                    </Text>
                )}
                {allServersLoading && allServers.length === 0 ? (
                    <div className="flex flex-col gap-2" role="status" aria-label="Loading shared servers…" aria-busy>
                        <Skeleton className="h-12" />
                        <Skeleton className="h-12" />
                    </div>
                ) : allServers.length === 0 ? (
                    <Empty>
                        <EmptyHeader>
                            <EmptyDescription>
                                No servers are registered with the gateway yet. Add a server before sharing access.
                            </EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                ) : (
                    <>
                        {sharedServers.length > 0 && (
                            <ItemGroup combined>
                                {sharedServers.map((server) => (
                                    <QuillGatewayAgentServerRow
                                        key={server.id}
                                        server={server}
                                        accountId={account.id}
                                        accountName={account.name}
                                        shared
                                        share={sharesByServerId[server.id]}
                                        connectionState={yourAgentConnectionState(account, currentUserId, server.id)}
                                        loading={agentServerAccessLoadingKeys.has(
                                            agentServerAccessKey(account.id, server.id)
                                        )}
                                        onSetAccess={setAgentServerAccess}
                                        onOpenServer={onOpenServer}
                                    />
                                ))}
                            </ItemGroup>
                        )}
                        {unsharedServers.length > 0 && (
                            <>
                                <Text size="xs" weight="semibold" variant="muted" render={<span className="m-0" />}>
                                    Not shared
                                </Text>
                                <ItemGroup combined>
                                    {unsharedServers.map((server) => (
                                        <QuillGatewayAgentServerRow
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
                                </ItemGroup>
                            </>
                        )}
                    </>
                )}
            </div>

            <div className="flex flex-col gap-2">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Recent tool calls
                </Heading>
                {recentCallsLoading && visibleRecentCalls.length === 0 ? (
                    <div className="flex flex-col gap-2">
                        <Skeleton className="h-10" />
                        <Skeleton className="h-10" />
                        <Skeleton className="h-10" />
                    </div>
                ) : (
                    <DataTable
                        columns={RECENT_CALL_COLUMNS}
                        data={visibleRecentCalls}
                        fullWidth
                        className="rounded-md border border-border"
                        empty={
                            <Empty>
                                <EmptyHeader>
                                    <EmptyDescription>
                                        No tool calls from this agent yet. Tool calls will appear here after the agent
                                        uses a server.
                                    </EmptyDescription>
                                </EmptyHeader>
                            </Empty>
                        }
                    />
                )}
                {visibleRecentCalls.length < recentCalls.length && (
                    <Button variant="default" className="self-center" onClick={showMoreRecentCalls}>
                        Show more
                    </Button>
                )}
            </div>
        </div>
    )
}
