import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSwitch, LemonTable, LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { mcpGatewayLogic } from './mcpGatewayLogic'
import { toProfileUser } from './gatewayUtils'

export function GatewayTeamAndAgents(): JSX.Element {
    const { serviceAccounts, members, serviceAccountsLoading, membersLoading } = useValues(mcpGatewayLogic)
    const { toggleAccountStatus, createServiceAccount } = useActions(mcpGatewayLogic)
    const [creating, setCreating] = useState(false)
    const [newName, setNewName] = useState('')

    return (
        <div className="flex flex-col gap-6">
            <div className="flex flex-col gap-2">
                <div className="flex items-center justify-between">
                    <h3 className="mb-0">Agents · {serviceAccounts.length}</h3>
                    {!creating && (
                        <LemonButton size="small" type="primary" onClick={() => setCreating(true)}>
                            + Create agent
                        </LemonButton>
                    )}
                </div>

                {creating && (
                    <div className="border border-dashed rounded p-3 flex flex-col gap-2">
                        <LemonInput placeholder="e.g. Docs Agent" value={newName} onChange={setNewName} autoFocus />
                        <div className="text-xs text-secondary font-mono">
                            {newName
                                ? `Will authenticate as svc-${newName
                                      .toLowerCase()
                                      .replace(/[^a-z0-9]+/g, '-')
                                      .replace(/^-|-$/g, '')}`
                                : 'The agent signs in with a generated svc-… identity.'}
                        </div>
                        <div className="flex gap-2">
                            <LemonButton
                                type="primary"
                                size="small"
                                disabledReason={!newName.trim() ? 'Enter a name' : undefined}
                                onClick={() => {
                                    createServiceAccount(newName.trim(), '')
                                    setCreating(false)
                                    setNewName('')
                                }}
                            >
                                + Create
                            </LemonButton>
                            <LemonButton
                                size="small"
                                onClick={() => {
                                    setCreating(false)
                                    setNewName('')
                                }}
                            >
                                Cancel
                            </LemonButton>
                        </div>
                    </div>
                )}

                <div className="border rounded divide-y">
                    {serviceAccounts.length === 0 && !serviceAccountsLoading ? (
                        <div className="p-4 text-sm text-secondary">No agents yet.</div>
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
                                <div className="text-xs text-secondary">
                                    {account.status === 'paused' ? 'Paused — all access off' : 'Active'}
                                </div>
                                <LemonSwitch
                                    checked={account.status === 'active'}
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
                            render: (_, member) => <ProfilePicture user={toProfileUser(member.user)} size="md" showName />,
                        },
                        {
                            title: 'Role',
                            key: 'role',
                            render: (_, member) =>
                                member.is_org_admin ? <LemonTag type="highlight">admin</LemonTag> : 'member',
                        },
                        {
                            title: 'Servers',
                            key: 'servers',
                            render: (_, member) => `${member.connected_server_ids.length} connected`,
                        },
                    ]}
                />
            </div>
        </div>
    )
}
