import { LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

/** A tool name as it appears in `$mcp_tool_call`, kept monospaced so near-identical names read apart. */
export function ToolTag({ name, className }: { name: string; className?: string }): JSX.Element {
    return (
        <LemonTag size="small" className={cn('max-w-full truncate font-mono', className)} title={name}>
            {name}
        </LemonTag>
    )
}
