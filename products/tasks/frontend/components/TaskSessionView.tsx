import { useEffect, useMemo, useState } from 'react'
import { TextMorph } from 'torph/react'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { LogEntry, parseLogs } from '../lib/parse-logs'
import { TaskRun } from '../types'
import { CollapsibleContent } from './CollapsibleContent'
import { ConsoleLogEntry } from './session/ConsoleLogEntry'
import { ToolCallEntry } from './session/ToolCallEntry'
import { TaskRunStatusBadge } from './TaskRunStatusBadge'

const HEDGEHOG_STATUSES = [
    'Spiking...',
    'Hedgehogging...',
    'Snuffling...',
    'Curling up...',
    'Foraging...',
    'Quilling...',
    'Hibernating...',
    'Scurrying...',
    'Bristling...',
    'Noodling...',
    'Hogwatching...',
    'Prickling...',
    'Burrowing...',
    'Snoot booping...',
    'Uncurling...',
]

function HedgehogStatus(): JSX.Element {
    const [statusIndex, setStatusIndex] = useState(() => Math.floor(Math.random() * HEDGEHOG_STATUSES.length))

    useEffect(() => {
        const interval = setInterval(() => {
            setStatusIndex((prev) => (prev + 1) % HEDGEHOG_STATUSES.length)
        }, 2000)
        return () => clearInterval(interval)
    }, [])

    return (
        <div className="flex items-center gap-2 py-2 text-muted">
            <Spinner className="text-xs" />
            <TextMorph as="span" className="text-xs">
                {HEDGEHOG_STATUSES[statusIndex]}
            </TextMorph>
        </div>
    )
}

interface TaskSessionViewProps {
    logs: string
    streamEntries: LogEntry[]
    isPolling: boolean
    isStreaming: boolean
    initialPrompt?: string | null
    run: TaskRun | null
}

export function filterDuplicateInitialPromptEntry(entries: LogEntry[], initialPrompt?: string | null): LogEntry[] {
    const normalizedPrompt = initialPrompt?.trim()
    if (!normalizedPrompt || entries.length === 0) {
        return entries
    }

    const [firstEntry, ...restEntries] = entries
    if (
        firstEntry.type !== 'user' ||
        firstEntry.message?.trim() !== normalizedPrompt ||
        (firstEntry.attachments?.length ?? 0) > 0
    ) {
        return entries
    }

    return restEntries
}

export function mergeDuplicateUserPromptEntries(entries: LogEntry[]): LogEntry[] {
    return entries.reduce<LogEntry[]>((mergedEntries, entry) => {
        const previousEntry = mergedEntries[mergedEntries.length - 1]

        if (
            previousEntry?.type === 'user' &&
            entry.type === 'user' &&
            previousEntry.message?.trim() === entry.message?.trim()
        ) {
            const previousHasAttachments = Boolean(previousEntry.attachments?.length)
            const currentHasAttachments = Boolean(entry.attachments?.length)

            if (!previousHasAttachments && currentHasAttachments) {
                mergedEntries[mergedEntries.length - 1] = entry
            } else if (previousHasAttachments && currentHasAttachments) {
                mergedEntries[mergedEntries.length - 1] = {
                    ...previousEntry,
                    attachments: [...(previousEntry.attachments ?? []), ...(entry.attachments ?? [])],
                }
            }

            return mergedEntries
        }

        mergedEntries.push(entry)
        return mergedEntries
    }, [])
}

function LogEntryRenderer({ entry }: { entry: LogEntry }): JSX.Element | null {
    switch (entry.type) {
        case 'console':
            return (
                <ConsoleLogEntry
                    level={entry.level || 'info'}
                    message={entry.message || ''}
                    timestamp={entry.timestamp}
                />
            )
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
                <div className="py-2 flex flex-col items-end">
                    <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs font-medium">User</span>
                        {entry.timestamp && (
                            <span className="text-xs text-muted">{new Date(entry.timestamp).toLocaleTimeString()}</span>
                        )}
                    </div>
                    <div className="border-r-2 border-muted pr-3 max-w-[90%] text-right">
                        <CollapsibleContent gradientColor="--bg-3000">
                            <div className="text-sm whitespace-pre-wrap">{entry.message}</div>
                        </CollapsibleContent>
                        {entry.attachments && entry.attachments.length > 0 ? (
                            <div className="mt-2 flex flex-wrap justify-end gap-2">
                                {entry.attachments.map((attachment) => (
                                    <LemonTag key={attachment.id} type="completion" size="small">
                                        {attachment.label}
                                    </LemonTag>
                                ))}
                            </div>
                        ) : null}
                    </div>
                </div>
            )
        case 'agent':
            return (
                <div className="py-2">
                    <div className="flex items-center gap-2 mb-1">
                        {entry.timestamp && (
                            <span className="text-xs text-muted">{new Date(entry.timestamp).toLocaleTimeString()}</span>
                        )}
                        <span className="text-xs font-medium">Agent</span>
                    </div>
                    <div className="border-l-2 border-primary pl-3 max-w-[90%]">
                        <div className="text-sm whitespace-pre-wrap">{entry.message}</div>
                    </div>
                </div>
            )
        case 'thinking':
            return (
                <div className="py-2">
                    <div className="flex items-center gap-2 mb-1">
                        {entry.timestamp && (
                            <span className="text-xs text-muted">{new Date(entry.timestamp).toLocaleTimeString()}</span>
                        )}
                        <span className="text-xs font-medium text-muted">Thinking</span>
                    </div>
                    <div className="border-l-2 border-muted pl-3 max-w-[90%]">
                        <CollapsibleContent gradientColor="--bg-3000">
                            <div className="text-sm whitespace-pre-wrap text-muted">{entry.message}</div>
                        </CollapsibleContent>
                    </div>
                </div>
            )
        case 'system':
            return (
                <div className="flex items-center gap-2 py-1">
                    {entry.timestamp && (
                        <span className="text-xs text-muted">{new Date(entry.timestamp).toLocaleTimeString()}</span>
                    )}
                    <span className="text-xs text-muted italic">{entry.message}</span>
                </div>
            )
        case 'raw':
            return <div className="py-0.5 text-xs font-mono text-muted break-all">{entry.raw}</div>
        default:
            return null
    }
}

export function TaskSessionView({
    logs,
    streamEntries,
    isPolling,
    isStreaming,
    initialPrompt,
    run,
}: TaskSessionViewProps): JSX.Element {
    const parsedLogs = useMemo(() => parseLogs(logs), [logs])
    // Use stream entries when available (real-time), otherwise fall back to parsed S3 logs
    const entries = useMemo(() => {
        const sourceEntries = streamEntries.length > 0 ? streamEntries : parsedLogs
        return filterDuplicateInitialPromptEntry(mergeDuplicateUserPromptEntries(sourceEntries), initialPrompt)
    }, [initialPrompt, parsedLogs, streamEntries])

    const handleCopyLogs = (): void => {
        navigator.clipboard.writeText(logs).then(
            () => lemonToast.success('Logs copied to clipboard'),
            () => lemonToast.error('Failed to copy logs')
        )
    }

    if (entries.length === 0) {
        return (
            <div className="p-4 text-center text-muted">
                <p>No logs available yet</p>
            </div>
        )
    }

    return (
        <div className="flex flex-col h-full">
            <div className="flex justify-between items-center px-4 py-2 border-b">
                <div className="flex items-center gap-2">
                    {run && <TaskRunStatusBadge run={run} />}
                    <span className="text-sm font-semibold">Logs ({entries.length})</span>
                </div>
                <LemonButton size="xsmall" icon={<IconCopy />} onClick={handleCopyLogs}>
                    Copy
                </LemonButton>
            </div>
            <div className="flex-1 overflow-auto p-4 font-mono text-sm bg-bg-3000">
                {entries.map((entry) => (
                    <LogEntryRenderer key={entry.id} entry={entry} />
                ))}
                {(isPolling || isStreaming) && <HedgehogStatus />}
            </div>
        </div>
    )
}
