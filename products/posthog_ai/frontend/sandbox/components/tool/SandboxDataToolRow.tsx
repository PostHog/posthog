import { type PropsWithChildren } from 'react'

import type { SandboxToolRendererProps } from '../../sandboxToolRegistry'
import { SandboxToolActivity } from './SandboxToolActivity'

/**
 * Shared shell for the data-tool adapters (insight, dashboard, recordings, query, error tracking,
 * notebook). Renders the registry icon + tool title as the header and the adapter's visualization as
 * always-visible content below it (via the Activity bridge), keeping data tools consistent with the
 * per-tool cards while each adapter keeps its own lazy chunk.
 */
export function SandboxDataToolRow({ children, ...props }: PropsWithChildren<SandboxToolRendererProps>): JSX.Element {
    const { message, icon, displayName, turnComplete, turnCancelled } = props

    return (
        <SandboxToolActivity
            message={message}
            icon={icon}
            title={message.title || displayName || 'Tool'}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        >
            {children}
        </SandboxToolActivity>
    )
}
