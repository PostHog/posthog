import { useEffect, useMemo, useState } from 'react'
import { TextMorph } from 'torph/react'

import { IconCopy } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { AcpMessage } from '../conversation/acp-types'
import { buildConversationItems } from '../conversation/buildConversationItems'
import { ConversationView } from '../conversation/ConversationView'
import { TaskRun } from '../types'
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
    /** Raw S3 log text, kept for the "Copy" affordance. */
    logs: string
    logsLoading: boolean
    /** Parsed ACP events (stream-first, S3 fallback) produced by the scene logic. */
    events: AcpMessage[]
    isPolling: boolean
    isStreaming: boolean
    run: TaskRun | null
}

export function TaskSessionView({
    logs,
    logsLoading,
    events,
    isPolling,
    isStreaming,
    run,
}: TaskSessionViewProps): JSX.Element {
    // Count rendered conversation items, not raw events: a single turn produces
    // many JSON-RPC messages (a chunk per streamed token, tool_call + tool_call_update
    // per tool), so events.length would wildly overstate what the user actually sees.
    const itemCount = useMemo(() => buildConversationItems(events, null).items.length, [events])

    const handleCopyLogs = (): void => {
        navigator.clipboard.writeText(logs).then(
            () => lemonToast.success('Logs copied to clipboard'),
            () => lemonToast.error('Failed to copy logs')
        )
    }

    if (events.length === 0) {
        if (logsLoading) {
            return (
                <div className="flex items-center justify-center h-32">
                    <Spinner />
                </div>
            )
        }
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
                    <span className="text-sm font-semibold">Logs ({itemCount})</span>
                </div>
                <LemonButton size="xsmall" icon={<IconCopy />} onClick={handleCopyLogs}>
                    Copy
                </LemonButton>
            </div>
            <div className="flex-1 overflow-hidden">
                {/* Cloud/replay semantics: the live polling/streaming state is surfaced by
                    HedgehogStatus below, so the conversation footer stays in its
                    completed-turn summary mode rather than double-rendering a spinner. */}
                <ConversationView events={events} isPromptPending={null} />
            </div>
            {(isPolling || isStreaming) && (
                <div className="px-4">
                    <HedgehogStatus />
                </div>
            )}
        </div>
    )
}
