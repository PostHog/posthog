import { dayjs } from 'lib/dayjs'

import { LogMessage } from '~/queries/schema/schema-general'

import { GenericMcpToolRenderer, ToolActivity } from 'products/posthog_ai/frontend/api/tools'
import type { ToolRendererProps } from 'products/posthog_ai/frontend/api/tools'

import { LogTag } from '../components/LogTag'
import { describeLogsQuery, extractLogRows, LogRowSummary } from './logsQueryToolOutput'

// The thread stays scannable, so the body lists a bounded window and names the remainder.
const MAX_ROWS = 15

function formatTimestamp(timestamp: string): string {
    const parsed = dayjs(timestamp)
    return parsed.isValid() ? parsed.format('MMM D HH:mm:ss') : timestamp
}

function LogRowsBody({ rows }: { rows: LogRowSummary[] }): JSX.Element {
    if (rows.length === 0) {
        return <div className="text-muted">No logs matched this query.</div>
    }

    const shown = rows.slice(0, MAX_ROWS)
    return (
        <div className="flex flex-col gap-1">
            {shown.map((row, index) => (
                <div key={index} className="flex items-baseline gap-2">
                    <LogTag level={row.severityText as LogMessage['severity_text']} />
                    <span className="text-muted text-xs font-mono shrink-0">{formatTimestamp(row.timestamp)}</span>
                    <span className="text-xs font-mono truncate flex-1">{row.body}</span>
                </div>
            ))}
            {rows.length > MAX_ROWS && (
                <div className="text-muted text-xs">+{rows.length - MAX_ROWS} more not shown</div>
            )}
        </div>
    )
}

/**
 * Result card for the `query-logs` tool: renders the returned log rows as a compact, severity-tagged
 * list in the collapsible body. Falls back to the generic card for a pending call or an output with no
 * `results` array.
 */
export function LogsQueryToolWidget(props: ToolRendererProps): JSX.Element {
    const { message, icon, displayName, turnComplete, turnCancelled } = props
    const rows = message.status === 'completed' ? extractLogRows(message) : null

    if (!rows) {
        return <GenericMcpToolRenderer {...props} />
    }

    return (
        <ToolActivity
            message={message}
            icon={icon}
            title={displayName ?? 'Query logs'}
            subtitle={describeLogsQuery(message)}
            body={<LogRowsBody rows={rows} />}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
}
