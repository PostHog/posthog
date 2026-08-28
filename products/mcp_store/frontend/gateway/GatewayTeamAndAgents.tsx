import { MakeLogicType, actions, kea, path, reducers, useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronRight, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch, LemonTable, LemonTag, ProfilePicture, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { GatewayMemberSummaryApi, MCPGatewayServerApi, MCPServiceAccountApi } from '../generated/api.schemas'
import { toProfileUser } from './gatewayUtils'
import { mcpGatewayLogic } from './mcpGatewayLogic'

const MEMBER_PREVIEW_LIMIT = 10

function memberDisplayName(member: GatewayMemberSummaryApi): string {
    return [member.user.first_name, member.user.last_name].filter(Boolean).join(' ').trim() || member.user.email
}

function agentToolCount(account: MCPServiceAccountApi, servers: MCPGatewayServerApi[]): number {
    const serverIds = new Set(account.server_ids)
    return servers.filter((server) => serverIds.has(server.id)).reduce((total, server) => total + server.tool_count, 0)
}

interface gatewayTeamAndAgentsLogicValues {
    memberSearch: string
    membersExpanded: boolean
}

interface gatewayTeamAndAgentsLogicActions {
    setMemberSearch: (memberSearch: string) => { memberSearch: string }
    toggleMembersExpanded: () => { value: true }
}

type gatewayTeamAndAgentsLogicType = MakeLogicType<gatewayTeamAndAgentsLogicValues, gatewayTeamAndAgentsLogicActions>

const gatewayTeamAndAgentsLogic = kea<gatewayTeamAndAgentsLogicType>([
    path(['products', 'mcp_store', 'frontend', 'gateway', 'gatewayTeamAndAgentsLogic']),
    actions({
        setMemberSearch: (memberSearch: string) => ({ memberSearch }),
        toggleMembersExpanded: true,
    }),
    reducers({
        memberSearch: ['', { setMemberSearch: (_, { memberSearch }) => memberSearch }],
        membersExpanded: [
            false,
            {
                setMemberSearch: () => false,
                toggleMembersExpanded: (expanded) => !expanded,
            },
        ],
    }),
])

export interface GatewayTeamAndAgentsProps {
    onOpenAgent?: (id: string) => void
    onOpenMember?: (id: number) => void
}

export function GatewayTeamAndAgents({ onOpenAgent, onOpenMember }: GatewayTeamAndAgentsProps = {}): JSX.Element {
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
    const normalizedMemberSearch = memberSearch.trim().toLowerCase()
    const filteredMembers = normalizedMemberSearch
        ? members.filter((member) => {
              const name = memberDisplayName(member).toLowerCase()
              return (
                  name.includes(normalizedMemberSearch) ||
                  member.user.email.toLowerCase().includes(normalizedMemberSearch)
              )
          })
        : members
    const displayedMembers = membersExpanded ? filteredMembers : filteredMembers.slice(0, MEMBER_PREVIEW_LIMIT)
    const openAgent = (id: string): void => {
        if (onOpenAgent) {
            onOpenAgent(id)
        } else {
            router.actions.push(urls.mcpGatewayAgent(id))
        }
    }
    const openMember = (id: number): void => {
        if (onOpenMember) {
            onOpenMember(id)
        } else {
            router.actions.push(urls.mcpGatewayMember(id))
        }
    }

    return (
        <div className="flex flex-col gap-6 min-w-0">
            <div className="flex flex-col gap-1">
                <h2 className="mb-0">Team & agents</h2>
                <p className="mb-0 text-secondary">Control access for your team members and PostHog agents.</p>
            </div>

            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                    <h3 className="mb-0">Agents</h3>
                    <LemonTag type="muted" size="small">
                        {serviceAccounts.length}
                    </LemonTag>
                </div>

                <div className="border rounded divide-y overflow-hidden">
                    {serviceAccountsLoading ? (
                        <div className="p-4 text-sm text-secondary flex items-center justify-center gap-2">
                            <Spinner /> Loading agents
                        </div>
                    ) : serviceAccounts.length === 0 ? (
                        <div className="p-4 text-sm text-secondary">
                            No PostHog agents are available for this project.
                        </div>
                    ) : (
                        serviceAccounts.map((account) => {
                            const active = account.status === 'active'
                            const statusLoading = accountStatusLoadingIds.has(account.id)
                            const toolCount = agentToolCount(account, servers)
                            // `server_ids` carries one entry per member grant, so the raw
                            // length overcounts servers shared by several members.
                            const serverCount = agentSharedServerCounts[account.id] ?? 0

                            return (
                                <div key={account.id} className="flex items-center gap-3 p-3">
                                    <div className="flex items-center justify-center bg-surface-secondary rounded w-10 h-10 shrink-0">
                                        <IconSparkles />
                                    </div>
                                    <LemonButton
                                        type="tertiary"
                                        fullWidth
                                        className="min-w-0 justify-start"
                                        onClick={() => openAgent(account.id)}
                                        sideIcon={<IconChevronRight />}
                                    >
                                        <div className="flex flex-col items-start min-w-0">
                                            <span className="font-semibold truncate max-w-full">{account.name}</span>
                                            <span className="text-xs text-secondary">
                                                {serverCount} server
                                                {serverCount === 1 ? '' : 's'} · {toolCount} tool
                                                {toolCount === 1 ? '' : 's'}
                                            </span>
                                        </div>
                                    </LemonButton>
                                    <div className="flex flex-col items-end gap-1 shrink-0">
                                        <LemonSwitch
                                            checked={active}
                                            loading={statusLoading}
                                            aria-label={`${active ? 'Pause' : 'Resume'} ${account.name}`}
                                            onChange={(checked) => {
                                                if (!statusLoading) {
                                                    toggleAccountStatus(account.id, !checked)
                                                }
                                            }}
                                        />
                                        {!active && (
                                            <span className="text-xs text-secondary">Paused. All access is off.</span>
                                        )}
                                    </div>
                                </div>
                            )
                        })
                    )}
                </div>
            </div>

            <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-2">
                        <h3 className="mb-0">Members</h3>
                        <LemonTag type="muted" size="small">
                            {memberCount}
                        </LemonTag>
                    </div>
                    <LemonInput
                        type="search"
                        placeholder="Search members"
                        value={memberSearch}
                        onChange={setMemberSearch}
                        size="small"
                        aria-label="Search members"
                    />
                </div>
                <LemonTable
                    loading={membersLoading}
                    dataSource={displayedMembers}
                    emptyState={
                        members.length === 0
                            ? 'No members found.'
                            : `No members match “${memberSearch.trim()}”. Clear the search and try again.`
                    }
                    onRow={(member) => ({
                        onClick: () => openMember(member.user.id),
                        className: 'cursor-pointer',
                    })}
                    columns={[
                        {
                            title: 'Member',
                            key: 'member',
                            render: (_, member) => (
                                <div className="flex items-center gap-2 min-w-0">
                                    <ProfilePicture user={toProfileUser(member.user)} size="md" />
                                    <div className="flex flex-col min-w-0">
                                        <span className="font-semibold truncate">{memberDisplayName(member)}</span>
                                        <span className="text-xs text-secondary truncate">{member.user.email}</span>
                                    </div>
                                </div>
                            ),
                        },
                        {
                            title: 'Role',
                            key: 'role',
                            render: (_, member) => (
                                <LemonTag type={member.is_org_admin ? 'highlight' : 'muted'}>
                                    {member.is_org_admin ? 'Admin' : 'Member'}
                                </LemonTag>
                            ),
                        },
                        {
                            title: 'Server access',
                            key: 'servers',
                            render: (_, member) => {
                                const allowed = Math.max(servers.length - member.revoked_server_ids.length, 0)
                                const connected = member.connected_server_ids.length
                                return (
                                    <span className="text-secondary">
                                        {allowed} of {servers.length} servers
                                        {connected > 0 ? ` · ${connected} connected` : ''}
                                    </span>
                                )
                            },
                        },
                        {
                            key: 'open',
                            width: 32,
                            render: (_, member) => (
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    icon={<IconChevronRight />}
                                    tooltip={`Open ${memberDisplayName(member)}`}
                                    aria-label={`Open ${memberDisplayName(member)}`}
                                    onClick={(event) => {
                                        event.stopPropagation()
                                        openMember(member.user.id)
                                    }}
                                />
                            ),
                        },
                    ]}
                />
                {filteredMembers.length > MEMBER_PREVIEW_LIMIT && (
                    <LemonButton size="small" type="tertiary" fullWidth onClick={toggleMembersExpanded}>
                        {membersExpanded ? 'Show fewer' : `View ${filteredMembers.length - MEMBER_PREVIEW_LIMIT} more`}
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
