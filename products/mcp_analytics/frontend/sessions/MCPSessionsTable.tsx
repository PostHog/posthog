import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import type { MCPSessionApi } from '../generated/api.schemas'
import { MCPSessionDetail } from './MCPSessionDetail'
import { mcpSessionsLogic, type MCPSessionSortColumn } from './mcpSessionsLogic'
import { formatDuration, sessionDurationMs } from './utils'

export function MCPSessionsTable(): JSX.Element {
    const { setFilters, loadSessions, selectSession, setSorting } = useActions(mcpSessionsLogic)
    const { sessions, sessionsLoading, filters, selectedSessionId, sorting } = useValues(mcpSessionsLogic)

    const columns: LemonTableColumns<MCPSessionApi> = [
        {
            title: 'Person',
            key: 'distinct_id',
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
            sorter: true,
        },
        {
            title: 'Started',
            key: 'session_start',
            render: (_, record) => <TZLabel time={record.session_start} />,
            sorter: true,
        },
        {
            title: 'Tool calls',
            key: 'tool_call_count',
            dataIndex: 'tool_calls',
            align: 'right',
            render: (_, record) => <span className="text-xs whitespace-nowrap">{record.tool_calls}</span>,
            sorter: true,
        },
        {
            title: 'Duration',
            key: 'duration_seconds',
            align: 'right',
            render: (_, record) => (
                <span className="text-xs whitespace-nowrap">
                    {formatDuration(sessionDurationMs(record.session_start, record.session_end))}
                </span>
            ),
            sorter: true,
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
                    loading={sessionsLoading}
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
                        loading={sessionsLoading}
                        sorting={sorting ? { columnKey: sorting.column, order: sorting.order } : null}
                        onSort={(newSorting) =>
                            setSorting(
                                newSorting
                                    ? {
                                          column: newSorting.columnKey as MCPSessionSortColumn,
                                          order: newSorting.order,
                                      }
                                    : null
                            )
                        }
                        useURLForSorting={false}
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
