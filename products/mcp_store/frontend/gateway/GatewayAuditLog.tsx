import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSnack, LemonTable, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { AuditCountsApi } from '../generated/api.schemas'
import { AUDIT_PAGE_SIZE, AuditQuickFilter, gatewayAuditLogic } from './gatewayAuditLogic'
import { DecisionTag, toProfileUser } from './gatewayUtils'

const FILTERS: { key: AuditQuickFilter; label: string; countKey: keyof AuditCountsApi }[] = [
    { key: 'all', label: 'All activity', countKey: 'all' },
    { key: 'agents', label: 'Agents only', countKey: 'agents' },
    { key: 'approvals', label: 'Approvals', countKey: 'approvals' },
    { key: 'blocked', label: 'Blocked', countKey: 'blocked' },
]

export function GatewayAuditLog(): JSX.Element {
    const { auditResponse, auditResponseLoading, counts, quickFilter, page } = useValues(gatewayAuditLogic)
    const { setQuickFilter, setPage } = useActions(gatewayAuditLogic)

    return (
        <div className="flex flex-col gap-4">
            <div className="text-sm text-secondary">
                Every tool call routed through the gateway — each row is one call to a tool on one of your team's MCP
                servers, and how the gateway decided it.
            </div>

            <div className="flex items-center gap-2 flex-wrap">
                {FILTERS.map((filter) => (
                    <LemonButton
                        key={filter.key}
                        size="small"
                        type={quickFilter === filter.key ? 'primary' : 'tertiary'}
                        onClick={() => setQuickFilter(filter.key)}
                    >
                        {filter.label}
                        {counts && <LemonSnack className="ml-1">{counts[filter.countKey] ?? 0}</LemonSnack>}
                    </LemonButton>
                ))}
            </div>

            <LemonTable
                loading={auditResponseLoading}
                dataSource={auditResponse.results}
                emptyState="No tool calls match these filters."
                pagination={{
                    controlled: true,
                    pageSize: AUDIT_PAGE_SIZE,
                    currentPage: page,
                    entryCount: auditResponse.count,
                    onForward: () => setPage(page + 1),
                    onBackward: () => setPage(page - 1),
                }}
                columns={[
                    {
                        title: 'Time',
                        dataIndex: 'created_at',
                        render: (_, row) => <TZLabel time={row.created_at} />,
                    },
                    {
                        title: 'Caller',
                        key: 'caller',
                        render: (_, row) =>
                            row.actor_service_account ? (
                                <span className="flex items-center gap-1">
                                    <IconSparkles />
                                    {row.actor_service_account.name}
                                </span>
                            ) : row.actor_user ? (
                                <ProfilePicture user={toProfileUser(row.actor_user)} size="sm" showName />
                            ) : (
                                <span className="text-secondary">{row.actor_label || 'Unknown'}</span>
                            ),
                    },
                    {
                        title: 'MCP server · tool',
                        key: 'server',
                        render: (_, row) => (
                            <div>
                                <div className="font-semibold text-xs">{row.server_name}</div>
                                <div className="font-mono text-xs text-secondary">{row.tool_name}()</div>
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
        </div>
    )
}
