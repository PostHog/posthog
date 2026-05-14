import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { humanFriendlyDuration } from 'lib/utils'

import type { MCPSessionApi } from '../generated/api.schemas'
import { MCPSessionDetail } from './MCPSessionDetail'
import { mcpSessionsLogic } from './mcpSessionsLogic'
import { sessionDurationMs } from './utils'

export function MCPSessionsTable(): JSX.Element {
    const { setFilters, loadSessions, selectSession } = useActions(mcpSessionsLogic)
    const { sessions, allSessionsLoading, filters, selectedSessionId } = useValues(mcpSessionsLogic)

    const columns: LemonTableColumns<MCPSessionApi> = [
        {
            title: 'Person',
            key: 'person',
            render: (_, record) => {
                const label = record.person_name || record.person_email
                if (label) {
                    return <span className="text-xs font-medium truncate">{label}</span>
                }
                if (record.distinct_id) {
                    return <span className="text-xs font-mono text-secondary truncate">{record.distinct_id}</span>
                }
                return <span className="text-secondary">—</span>
            },
            sorter: (a, b) => {
                const labelA = a.person_name || a.person_email || a.distinct_id
                const labelB = b.person_name || b.person_email || b.distinct_id
                return labelA.localeCompare(labelB)
            },
        },
        {
            title: 'Started',
            key: 'session_start',
            render: (_, record) => <TZLabel time={record.session_start} />,
            sorter: (a, b) => a.session_start.localeCompare(b.session_start),
        },
        {
            title: 'Tool calls',
            key: 'tool_calls',
            dataIndex: 'tool_calls',
            align: 'right',
            render: (_, record) => <span className="text-xs whitespace-nowrap">{record.tool_calls}</span>,
            sorter: (a, b) => a.tool_calls - b.tool_calls,
        },
        {
            title: 'Duration',
            key: 'duration',
            align: 'right',
            render: (_, record) => (
                <span className="text-xs whitespace-nowrap">
                    {humanFriendlyDuration(sessionDurationMs(record.session_start, record.session_end) / 1000, {
                        secondsFixed: 1,
                    })}
                </span>
            ),
            sorter: (a, b) =>
                sessionDurationMs(a.session_start, a.session_end) - sessionDurationMs(b.session_start, b.session_end),
        },
    ]

    return (
        <div className="flex flex-col gap-3">
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
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start">
                <div className="flex-1 min-w-0">
                    <LemonTable
                        data-attr="mcp-sessions-table"
                        size="small"
                        pagination={{ pageSize: 20 }}
                        dataSource={sessions}
                        rowKey="session_id"
                        columns={columns}
                        loading={allSessionsLoading}
                        defaultSorting={{ columnKey: 'session_start', order: -1 }}
                        emptyState="No MCP sessions yet — try the seed_mcp_sessions management command for local data."
                        nouns={['session', 'sessions']}
                        onRow={(record) => ({
                            onClick: () => selectSession(record.session_id),
                        })}
                        rowClassName={(record) =>
                            record.session_id === selectedSessionId
                                ? 'cursor-pointer bg-accent-highlight-secondary'
                                : 'cursor-pointer'
                        }
                    />
                </div>
                <aside className="w-full lg:w-[480px] flex flex-col rounded border border-primary bg-surface-primary overflow-hidden">
                    <MCPSessionDetail />
                </aside>
            </div>
        </div>
    )
}
