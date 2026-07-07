import { type PropsWithChildren } from 'react'

import { ToolActivity } from './ToolActivity'
import type { ToolRendererProps } from './toolRegistry'

/**
 * Shared shell for the data-tool adapters (insight, dashboard, recordings, query, error tracking,
 * notebook). Renders the registry icon + tool title as the header and the adapter's visualization as
 * always-visible content below it (via the Activity bridge), keeping data tools consistent with the
 * per-tool cards while each adapter keeps its own lazy chunk.
 */
export function DataToolRow({ children, ...props }: PropsWithChildren<ToolRendererProps>): JSX.Element {
    const { message, icon, displayName, turnComplete, turnCancelled } = props

    // Single-exec inner tools carry the outer tool's frame title (a bare "exec") — the registry
    // display name or the resolved inner tool name is the meaningful label there.
    const title = message.innerToolName ? displayName || message.innerToolName : message.title || displayName || 'Tool'

    return (
        <ToolActivity
            message={message}
            icon={icon}
            title={title}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        >
            {children}
        </ToolActivity>
    )
}
