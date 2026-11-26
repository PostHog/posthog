import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import {
    Badge,
    Button,
    CardGroup,
    DataTable,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Heading,
    Input,
    Skeleton,
    Text,
    DataTableProps,
} from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'

import { GatewayMemberSummaryApi } from '../generated/api.schemas'
import {
    GatewayTeamAndAgentsProps,
    MEMBER_PREVIEW_LIMIT,
    agentToolCount,
    filterGatewayMembers,
    gatewayTeamAndAgentsLogic,
    memberDisplayName,
    openGatewayAgent,
    openGatewayMember,
} from './GatewayTeamAndAgents'
import { mcpGatewayLogic } from './mcpGatewayLogic'
import { QuillGatewayAgentRow } from './QuillGatewayAgentRow'

export function QuillGatewayTeamAndAgents({ onOpenAgent, onOpenMember }: GatewayTeamAndAgentsProps = {}): JSX.Element {
    const {
        agentSharedServerCounts,
        serviceAccounts,
        servers,
        members,
        memberCount,
        serviceAccountsLoading,
        membersLoading,
        accountStatusLoadingIds,
    } = useValues(mcpGatewayLogic)
    const { toggleAccountStatus } = useActions(mcpGatewayLogic)
    const { memberSearch, membersExpanded } = useValues(gatewayTeamAndAgentsLogic)
    const { setMemberSearch, toggleMembersExpanded } = useActions(gatewayTeamAndAgentsLogic)

    const filteredMembers = filterGatewayMembers(members, memberSearch)
    const displayedMembers = membersExpanded ? filteredMembers : filteredMembers.slice(0, MEMBER_PREVIEW_LIMIT)
    const openAgent = (id: string): void => openGatewayAgent(id, onOpenAgent)
    const openMember = (id: number): void => openGatewayMember(id, onOpenMember)

    const columns: DataTableProps<GatewayMemberSummaryApi, unknown>['columns'] = [
        {
            id: 'member',
            header: 'Member',
            meta: { expand: true },
            cell: ({ row }) => (
                <div className="flex min-w-0 items-center gap-2">
                    <QuillPersonAvatar name={memberDisplayName(row.original)} email={row.original.user.email} />
                    <div className="flex min-w-0 flex-col">
                        <Text size="xs" weight="medium" className="m-0 truncate" render={<span />}>
                            {memberDisplayName(row.original)}
                        </Text>
                        <Text size="xs" variant="muted" className="m-0 truncate" render={<span />}>
                            {row.original.user.email}
                        </Text>
                    </div>
                </div>
            ),
        },
        {
            id: 'role',
            header: 'Role',
            cell: ({ row }) => (
                <Badge variant={row.original.is_org_admin ? 'info' : 'default'}>
                    {row.original.is_org_admin ? 'Admin' : 'Member'}
                </Badge>
            ),
        },
        {
            id: 'servers',
            header: 'Server access',
            cell: ({ row }) => {
                const allowed = Math.max(servers.length - row.original.revoked_server_ids.length, 0)
                const connected = row.original.connected_server_ids.length

                return (
                    <Text size="xs" variant="muted" render={<span className="m-0" />}>
                        {`${allowed} of ${servers.length} servers${connected > 0 ? ` · ${connected} connected` : ''}`}
                    </Text>
                )
            },
        },
        {
            id: 'open',
            header: () => <span className="sr-only">Open</span>,
            cell: ({ row }) => (
                <Button
                    size="icon-sm"
                    tooltip={`Open ${memberDisplayName(row.original)}`}
                    aria-label={`Open ${memberDisplayName(row.original)}`}
                    onClick={(event) => {
                        event.stopPropagation()
                        openMember(row.original.user.id)
                    }}
                >
                    <IconChevronRight />
                </Button>
            ),
        },
    ]

    return (
        <div className="flex min-w-0 flex-col gap-6">
            <div className="flex flex-col gap-1">
                <Heading size="sm" render={<h3 className="m-0" />}>
                    Team & agents
                </Heading>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Control access for your team members and PostHog agents.
                </Text>
            </div>

            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                    <Heading size="sm" render={<h3 className="m-0" />}>
                        Agents
                    </Heading>
                    <Badge>{serviceAccounts.length}</Badge>
                </div>

                {serviceAccountsLoading ? (
                    <div className="flex flex-col gap-2">
                        <Skeleton className="h-14" />
                        <Skeleton className="h-14" />
                    </div>
                ) : serviceAccounts.length === 0 ? (
                    <Empty>
                        <EmptyHeader>
                            <EmptyDescription>No PostHog agents are available for this project.</EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                ) : (
                    <CardGroup size="sm">
                        {serviceAccounts.map((account) => {
                            const statusLoading = accountStatusLoadingIds.has(account.id)

                            return (
                                <QuillGatewayAgentRow
                                    key={account.id}
                                    account={account}
                                    // `server_ids` carries one entry per member grant, so the raw
                                    // length overcounts servers shared by several members.
                                    serverCount={agentSharedServerCounts[account.id] ?? 0}
                                    toolCount={agentToolCount(account, servers)}
                                    statusLoading={statusLoading}
                                    onOpen={() => openAgent(account.id)}
                                    onToggleStatus={(checked) => {
                                        if (!statusLoading) {
                                            toggleAccountStatus(account.id, !checked)
                                        }
                                    }}
                                />
                            )
                        })}
                    </CardGroup>
                )}
            </div>

            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                        <Heading size="sm" render={<h3 className="m-0" />}>
                            Members
                        </Heading>
                        <Badge>{memberCount}</Badge>
                    </div>
                    <Input
                        type="search"
                        size="sm"
                        className="w-auto"
                        placeholder="Search members"
                        value={memberSearch}
                        onChange={(event) => setMemberSearch(event.target.value)}
                        aria-label="Search members"
                    />
                </div>
                {membersLoading && members.length === 0 ? (
                    <div className="flex flex-col gap-2">
                        <Skeleton className="h-10" />
                        <Skeleton className="h-10" />
                        <Skeleton className="h-10" />
                    </div>
                ) : (
                    <DataTable
                        columns={columns}
                        data={displayedMembers}
                        fullWidth
                        className="rounded-md border border-border"
                        onRowClick={(member) => openMember(member.user.id)}
                        empty={
                            <Empty>
                                <EmptyHeader>
                                    <EmptyDescription>
                                        {members.length === 0
                                            ? 'No members found.'
                                            : `No members match “${memberSearch.trim()}”. Clear the search and try again.`}
                                    </EmptyDescription>
                                </EmptyHeader>
                            </Empty>
                        }
                    />
                )}
                {filteredMembers.length > MEMBER_PREVIEW_LIMIT && (
                    <Button className="w-full" onClick={toggleMembersExpanded}>
                        {membersExpanded ? 'Show fewer' : `View ${filteredMembers.length - MEMBER_PREVIEW_LIMIT} more`}
                    </Button>
                )}
            </div>
        </div>
    )
}
