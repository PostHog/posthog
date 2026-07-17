// Side-effect: registers the surface's product data-tool renderers (insight/dashboard/recordings/etc.)
// into the shared toolRegistry. Placed at the render chokepoint so every surface that renders a tool
// card (the /tasks runner, the signals inbox, Max's sandbox path) resolves those widgets.
import './widgets/registerDataToolRenderers'

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
    // `innerToolName` is set only when `resolveToolKey` parsed this key out of a trusted PostHog exec
    // command, so it doubles as the "first-party origin" signal that gates the product-widget entries.
    const entry = lookupToolRenderer(message.resolvedKey, message.innerToolName != null)
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
