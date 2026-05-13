import { useMemo } from 'react'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { LogEntry } from '../lib/parse-logs'
import { CollapsibleContent } from './CollapsibleContent'

export function extractConversationSummary(entries: LogEntry[]): LogEntry[] {
    return entries.filter(
        (entry) =>
            (entry.type === 'user' || entry.type === 'agent') &&
            typeof entry.message === 'string' &&
            entry.message.trim().length > 0
    )
}

function SummaryMessage({ entry }: { entry: LogEntry }): JSX.Element {
    const timestamp = entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : null
    const isUser = entry.type === 'user'

    return (
        <div className={`py-2 flex flex-col ${isUser ? 'items-end' : 'items-start'}`}>
            <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-medium">{isUser ? 'User' : 'Agent'}</span>
                {timestamp && <span className="text-xs text-muted">{timestamp}</span>}
            </div>
            <div
                className={`max-w-[90%] ${
                    isUser ? 'border-r-2 border-muted pr-3 text-right' : 'border-l-2 border-primary pl-3'
                }`}
            >
                <CollapsibleContent gradientColor="--bg-3000">
                    <LemonMarkdown lowKeyHeadings className="text-sm whitespace-pre-wrap">
                        {entry.message ?? ''}
                    </LemonMarkdown>
                </CollapsibleContent>
            </div>
        </div>
    )
}

export function TaskSummaryView({ entries }: { entries: LogEntry[] }): JSX.Element {
    const summaryEntries = useMemo(() => extractConversationSummary(entries), [entries])

    if (summaryEntries.length === 0) {
        return (
            <div className="p-4 text-center text-muted">
                <p>No conversation messages yet.</p>
            </div>
        )
    }

    return (
        <div className="flex flex-col font-sans">
            <div className="text-xs text-muted mb-2">
                Showing {summaryEntries.length} message{summaryEntries.length === 1 ? '' : 's'} between you and the
                agent. Tool calls, thinking, and console logs are hidden — switch to the Logs tab for the full trace.
            </div>
            {summaryEntries.map((entry) => (
                <SummaryMessage key={entry.id} entry={entry} />
            ))}
        </div>
    )
}
