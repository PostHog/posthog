import clsx from 'clsx'
import type { ReactNode } from 'react'

/** Monospace, scrollable output block for a tool card's collapsible body (terminal/search/fetch). */
export function ToolOutput({ children }: { children: ReactNode }): JSX.Element {
    return (
        <pre className="m-0 font-mono text-xs leading-relaxed text-secondary whitespace-pre-wrap break-all max-h-64 overflow-auto">
            {children}
        </pre>
    )
}

/** Vertical container stacking a tool card's body sections (input, output) with consistent spacing. */
export function ToolBody({ children }: { children: ReactNode }): JSX.Element {
    return <div className="flex flex-col gap-2 min-w-0">{children}</div>
}

/** A `ToolBody` section; `divided` draws a top border to separate it from the section above it. */
export function ToolBodySection({
    divided = false,
    children,
}: {
    divided?: boolean
    children: ReactNode
}): JSX.Element {
    return <div className={clsx('min-w-0', divided && 'border-t border-border-secondary pt-2')}>{children}</div>
}
