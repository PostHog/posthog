import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconSparkles } from '@posthog/icons'
import { LemonSwitch, LemonTable, LemonTag, ProfilePicture, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { toProfileUser } from './gatewayUtils'
import { mcpGatewayLogic } from './mcpGatewayLogic'

export function GatewayTeamAndAgents(): JSX.Element {
    const { serviceAccounts, members, serviceAccountsLoading, membersLoading, accountStatusLoadingIds } =
        useValues(mcpGatewayLogic)
    const { toggleAccountStatus } = useActions(mcpGatewayLogic)

    return (
        <div className="flex flex-col gap-6">
            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Agents · {serviceAccounts.length}</h3>

                <div className="border rounded divide-y">
                    {serviceAccountsLoading ? (
                        <div className="p-4 text-sm text-secondary flex items-center gap-2">
                            <Spinner /> Loading agents…
                        </div>
                    ) : serviceAccounts.length === 0 ? (
                        <div className="p-4 text-sm text-secondary">
                            No PostHog agents are available for this project.
                        </div>
                    ) : (
                        serviceAccounts.map((account) => (
                            <div key={account.id} className="flex items-center gap-3 p-3">
                                <div className="flex items-center justify-center bg-surface-secondary rounded w-9 h-9">
                                    <IconSparkles />
                                </div>
                                <button
                                    className="flex-1 text-left"
                                    onClick={() => router.actions.push(urls.mcpGatewayAgent(account.id))}
                                >
                                    <div className="font-semibold hover:text-accent">{account.name}</div>
                                    <div className="text-xs text-secondary">
                                        {account.server_ids.length} server{account.server_ids.length === 1 ? '' : 's'}
                                    </div>
                                </button>
                                <div className="flex items-center justify-end gap-1 flex-wrap">
                                    <LemonTag type={account.product_enabled ? 'success' : 'muted'} size="small">
                                        {account.product_enabled ? 'Product available' : 'Product unavailable'}
                                    </LemonTag>
                                    <LemonTag type={account.status === 'paused' ? 'warning' : 'success'} size="small">
                                        {account.status === 'paused' ? 'MCP paused' : 'MCP enabled'}
                                    </LemonTag>
                                </div>
                                <LemonSwitch
                                    checked={account.status === 'active'}
                                    loading={accountStatusLoadingIds.has(account.id)}
                                    disabledReason={
                                        account.status === 'paused' && !account.product_enabled
                                            ? account.product_disabled_reason ||
                                              'Enable this agent’s PostHog product before resuming it.'
                                            : undefined
                                    }
                                    aria-label={`${account.status === 'active' ? 'Pause' : 'Resume'} ${account.name}`}
                                    onChange={(checked) => toggleAccountStatus(account.id, !checked)}
                                />
                            </div>
                        ))
                    )}
                </div>
            </div>

            <div className="flex flex-col gap-2">
                <h3 className="mb-0">Members · {members.length}</h3>
                <LemonTable
                    loading={membersLoading}
                    dataSource={members}
                    emptyState="No members found."
                    onRow={(member) => ({
                        onClick: () => router.actions.push(urls.mcpGatewayMember(member.user.id)),
                        className: 'cursor-pointer',
                    })}
                    columns={[
                        {
                            title: 'Member',
                            key: 'member',
                            render: (_, member) => (
                                <ProfilePicture user={toProfileUser(member.user)} size="md" showName />
                            ),
                        },
                        {
                            title: 'Role',
                            key: 'role',
                            render: (_, member) =>
                                member.is_org_admin ? <LemonTag type="highlight">admin</LemonTag> : 'member',
                        },
                        {
                            title: 'Personal connections',
                            key: 'servers',
                            render: (_, member) => member.connected_server_ids.length,
                        },
                    ]}
                />
            </div>
        </div>
    )
}
