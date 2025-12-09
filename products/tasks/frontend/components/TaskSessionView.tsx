import { IconCopy } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'
import { useMemo } from 'react'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { LogEntry, parseLogs } from '../lib/parse-logs'
import { ConsoleLogEntry } from './session/ConsoleLogEntry'
import { ToolCallEntry } from './session/ToolCallEntry'

interface TaskSessionViewProps {
    logs: string
    loading: boolean
    isPolling: boolean
}

function LogEntryRenderer({ entry }: { entry: LogEntry }): JSX.Element | null {
    switch (entry.type) {
        case 'console':
            return <ConsoleLogEntry level={entry.level || 'info'} message={entry.message || ''} timestamp={entry.timestamp} />
        case 'tool':
            return (
                <ToolCallEntry
                    toolName={entry.toolName || 'unknown'}
                    status={entry.toolStatus || 'pending'}
                    args={entry.toolArgs}
                    result={entry.toolResult}
                    timestamp={entry.timestamp}
                />
            )
        case 'user':
            return (
                <div className="bg-accent-highlight rounded-lg px-3 py-2 mt-4 max-w-[80%]">
                    <div className="text-xs text-muted mb-1">User</div>
                    <div className="text-sm">{entry.message}</div>
                </div>
            )
        case 'agent':
            return (
                <div className="py-2">
                    <div className="text-xs text-muted mb-1">Agent</div>
                    <div className="text-sm whitespace-pre-wrap">{entry.message}</div>
                </div>
            )
        case 'system':
            return (
                <div className="py-1 text-xs text-muted italic">
                    {entry.message}
                </div>
            )
        case 'raw':
            return <div className="py-0.5 text-xs font-mono text-muted">{entry.raw}</div>
        default:
            return null
    }
}

export function TaskSessionView({ logs, loading, isPolling }: TaskSessionViewProps): JSX.Element {
    const entries = useMemo(() => parseLogs(logs), [logs])

    const handleCopyLogs = (): void => {
        navigator.clipboard.writeText(logs)
        lemonToast.success('Logs copied to clipboard')
    }

    if (loading && entries.length === 0) {
        return (
            <div className="flex items-center justify-center p-8">
                <Spinner />
            </div>
        )
    }

    if (entries.length === 0) {
        return (
            <div className="p-4 text-center text-muted">
                <p>No logs available yet</p>
                {isPolling && <p className="text-xs mt-2">Waiting for logs...</p>}
            </div>
        )
    }

    return (
        <div className="flex flex-col h-full">
            <div className="flex justify-between items-center px-4 py-2 border-b">
                <span className="text-sm font-semibold">Logs ({entries.length})</span>
                <LemonButton size="xsmall" icon={<IconCopy />} onClick={handleCopyLogs}>
                    Copy
                </LemonButton>
            </div>
            <div className="flex-1 overflow-auto p-4 font-mono text-sm bg-bg-3000">
                {entries.map((entry) => (
                    <LogEntryRenderer key={entry.id} entry={entry} />
                ))}
                {isPolling && (
                    <div className="flex items-center gap-2 py-2 text-muted">
                        <Spinner className="text-xs" />
                        <span className="text-xs">Loading more...</span>
                    </div>
                )}
            </div>
        </div>
    )
}
