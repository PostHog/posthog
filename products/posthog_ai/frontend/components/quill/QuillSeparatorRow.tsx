import { ChatMarker, ChatMarkerContent } from '@posthog/quill-primitives'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { ThreadItem } from '../../types/streamTypes'
import { isRunningStatus, isStartupStatus } from '../../utils/groupThreadActivity'

const RUNNING_LABELS: Record<string, string> = {
    compacting: 'Compacting conversation history…',
    clearing: 'Clearing conversation…',
    setup_hooks: 'Running repository setup…',
    sdk_initialization: 'Starting the agent…',
}

const SETTLED_LABELS: Record<string, string> = {
    compacting_failed: "Couldn't compact the conversation",
    refusal: 'The model declined this request. Rephrase it, or switch models and try again.',
    refusal_fallback: 'Request declined, retried with the fallback model',
}

function statusLabel(item: ThreadItem, live: boolean): { label: string; running: boolean } {
    const status = item.status ?? ''
    if (isStartupStatus(item)) {
        return live ? { label: RUNNING_LABELS[status], running: true } : { label: 'Agent started', running: false }
    }
    if (isRunningStatus(item)) {
        return { label: RUNNING_LABELS[status], running: true }
    }
    if (status === 'extension_notice' && item.message) {
        return { label: item.message, running: false }
    }
    // A failed clear leaves the agent session closed, so the way forward is a new run, not a retry.
    if (status === 'clearing_failed') {
        const reason = item.errorMessage
            ? `Couldn't clear the conversation: ${item.errorMessage}`
            : "Couldn't clear the conversation"
        return { label: `${reason}. Start a new run to keep going.`, running: false }
    }
    const label = SETTLED_LABELS[status] ?? status.replaceAll('_', ' ')
    return { label: label.charAt(0).toUpperCase() + label.slice(1), running: false }
}

function separatorLabel(item: ThreadItem, live: boolean): { label: string; running: boolean } {
    if (item.type === 'compact_boundary') {
        const parts = [
            'Conversation compacted',
            item.trigger,
            typeof item.preTokens === 'number'
                ? `~${humanFriendlyNumber(item.preTokens)}\u00a0tokens summarized`
                : null,
        ]
        // The non-breaking space keeps each dot on the line it follows when the label wraps.
        return { label: parts.filter(Boolean).join('\u00a0· '), running: false }
    }
    if (item.type === 'conversation_cleared') {
        return { label: 'Conversation cleared', running: false }
    }
    return statusLabel(item, live)
}

/** `live` keeps a startup phase reading as in progress until the agent's output follows it. */
export function QuillSeparatorRow({ item, live }: { item: ThreadItem; live: boolean }): JSX.Element {
    const { label, running } = separatorLabel(item, live)
    return (
        // A long label wraps between the rules instead of running past the edge of a narrow thread.
        <ChatMarker
            variant="separator"
            status={running ? 'running' : undefined}
            className="before:min-w-4 after:min-w-4"
        >
            <ChatMarkerContent className="max-w-[80%] shrink">{label}</ChatMarkerContent>
        </ChatMarker>
    )
}
