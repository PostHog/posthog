import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import type { MCPSessionApi } from '../generated/api.schemas'
import { mcpSessionsLogic } from './mcpSessionsLogic'

function shortenSessionId(sessionId: string): string {
    if (sessionId.length <= 13) {
        return sessionId
    }
    return `${sessionId.slice(0, 8)}…${sessionId.slice(-4)}`
}

export function MCPSessionsTable(): JSX.Element {
    const { setFilters, loadSessions } = useActions(mcpSessionsLogic)
    const { sessions, allSessionsLoading, filters } = useValues(mcpSessionsLogic)

    const columns: LemonTableColumns<MCPSessionApi> = [
        {
            title: 'Session',
            key: 'session_id',
            dataIndex: 'session_id',
            render: (_, record) => (
                <CopyToClipboardInline
                    explicitValue={record.session_id}
                    description="session id"
                    tooltipMessage={record.session_id}
                    iconSize="xsmall"
                    className="font-mono text-xs whitespace-nowrap"
                >
                    {shortenSessionId(record.session_id)}
                </CopyToClipboardInline>
            ),
        },
        {
            title: 'Client',
            key: 'mcp_client_name',
            dataIndex: 'mcp_client_name',
            width: 220,
            render: (_, record) =>
                record.mcp_client_name ? (
                    <span className="whitespace-nowrap">{record.mcp_client_name}</span>
                ) : (
                    <span className="text-secondary">—</span>
                ),
            sorter: (a, b) => (a.mcp_client_name || '').localeCompare(b.mcp_client_name || ''),
        },
        {
            title: 'Tool calls',
            key: 'event_count',
            dataIndex: 'event_count',
            align: 'right',
            sorter: (a, b) => a.event_count - b.event_count,
        },
        {
            title: 'Tools used',
            key: 'tools_used',
            dataIndex: 'tools_used',
            render: (_, record) => (
                <div className="flex flex-wrap gap-1">
                    {record.tools_used.map((tool) => (
                        <LemonTag key={tool} type="option" size="small">
                            {tool}
                        </LemonTag>
                    ))}
                </div>
            ),
        },
        {
            title: 'First seen',
            key: 'first_seen',
            dataIndex: 'first_seen',
            render: (_, record) => <TZLabel time={record.first_seen} />,
            sorter: (a, b) => a.first_seen.localeCompare(b.first_seen),
        },
        {
            title: 'Last seen',
            key: 'last_seen',
            dataIndex: 'last_seen',
            render: (_, record) => <TZLabel time={record.last_seen} />,
            sorter: (a, b) => a.last_seen.localeCompare(b.last_seen),
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex justify-between gap-2 flex-wrap">
                <LemonInput
                    type="search"
                    className="w-96 !max-w-none"
                    placeholder="Search by session id, client, or tool"
                    onChange={(value) => setFilters({ search: value })}
                    value={filters.search}
                />
                <LemonButton
                    type="secondary"
                    icon={<IconRefresh />}
                    onClick={() => loadSessions()}
                    loading={allSessionsLoading}
                    size="small"
                >
                    Reload
                </LemonButton>
            </div>
            <LemonTable
                data-attr="mcp-sessions-table"
                pagination={{ pageSize: 25 }}
                dataSource={sessions}
                rowKey="session_id"
                columns={columns}
                loading={allSessionsLoading}
                defaultSorting={{ columnKey: 'last_seen', order: -1 }}
                emptyState="No MCP sessions yet — try the seed_mcp_sessions management command for local data."
                nouns={['session', 'sessions']}
            />
        </div>
    )
}
