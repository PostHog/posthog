import { Suspense, memo } from 'react'

import type { SandboxToolCallMessage } from 'products/posthog_ai/frontend/sandbox/types/sandboxToolTypes'

import { lookupSandboxToolRenderer } from '../../sandboxToolRegistry'
import { ToolCardSkeleton } from './ToolCardSkeleton'

export interface SandboxToolCallProps {
    message: SandboxToolCallMessage
    /** Turn-level signals for resolving a still-incomplete tool as loading vs cancelled vs idle. */
    turnComplete?: boolean
    turnCancelled?: boolean
}

/**
 * Eager dispatch for a single sandbox tool call: resolves the registry entry by `resolvedKey`, then
 * renders its (lazy) renderer inside a `Suspense` boundary that shows a `ToolCardSkeleton` while the
 * chunk loads. Replaces the inline `tool_invocation` branch in `SandboxThread`.
 */
export const SandboxToolCall = memo(function SandboxToolCall({
    message,
    turnComplete,
    turnCancelled,
}: SandboxToolCallProps): JSX.Element {
    const entry = lookupSandboxToolRenderer(message.resolvedKey)
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
