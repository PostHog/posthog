import { Suspense, memo } from 'react'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { ToolCardSkeleton } from './ToolCardSkeleton'
import { lookupToolRenderer } from './toolRegistry'

export interface ToolCallCardProps {
    message: ToolCallMessage
    /** Turn-level signals for resolving a still-incomplete tool as loading vs cancelled vs idle. */
    turnComplete?: boolean
    turnCancelled?: boolean
}

/**
 * Eager dispatch for a single sandbox tool call: resolves the registry entry by `resolvedKey`, then
 * renders its (lazy) renderer inside a `Suspense` boundary that shows a `ToolCardSkeleton` while the
 * chunk loads. Replaces the inline `tool_invocation` branch in `ThreadView`.
 */
export const ToolCallCard = memo(function ToolCallCard({
    message,
    turnComplete,
    turnCancelled,
}: ToolCallCardProps): JSX.Element {
    const entry = lookupToolRenderer(message.resolvedKey)
    return (
        <Suspense fallback={<ToolCardSkeleton icon={entry.icon} displayName={entry.displayName} />}>
            <entry.Renderer
                message={message}
                isLastInGroup
                icon={entry.icon}
                displayName={entry.displayName}
                turnComplete={turnComplete}
                turnCancelled={turnCancelled}
            />
        </Suspense>
    )
})
