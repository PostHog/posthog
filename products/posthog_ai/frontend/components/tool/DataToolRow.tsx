import { type PropsWithChildren } from 'react'

import { getMcpToolPresentation } from './GenericMcpToolRenderer'
import { ToolActivity } from './ToolActivity'
import type { ToolRendererProps } from './toolRegistry'

/**
 * Shared shell for the data-tool adapters (insight, dashboard, recordings, query, error tracking,
 * notebook). Renders the same header/accordion as the generic MCP card — `Call <tool>` title,
 * compact input preview, expandable input/output body — with the adapter's visualization as
 * always-visible content below it (via the Activity bridge), while each adapter keeps its own
 * lazy chunk.
 */
export function DataToolRow({ children, ...props }: PropsWithChildren<ToolRendererProps>): JSX.Element {
    const { message, icon, displayName, turnComplete, turnCancelled } = props
    const { title, subtitle, body } = getMcpToolPresentation(message, displayName)

    return (
        <ToolActivity
            message={message}
            icon={icon}
            title={title}
            subtitle={subtitle}
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        >
            {children}
        </ToolActivity>
    )
}
