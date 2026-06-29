import type { ReactNode } from 'react'

/** Monospace, scrollable output block for a tool card's collapsible body (terminal/search/fetch). */
export function ToolOutput({ children }: { children: ReactNode }): JSX.Element {
    return (
        <pre className="m-0 font-mono text-xs leading-relaxed text-secondary whitespace-pre-wrap break-all max-h-64 overflow-auto">
            {children}
        </pre>
    )
}
