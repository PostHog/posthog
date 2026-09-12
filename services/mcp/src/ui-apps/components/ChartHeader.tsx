import type { ReactElement, ReactNode } from 'react'

interface ChartHeaderProps {
    title: string
    /** Right-aligned controls (chart-type select, options, …). Omit for visualizations with none. */
    children?: ReactNode
}

export function ChartHeader({ title, children }: ChartHeaderProps): ReactElement {
    return (
        <div className="mb-2 flex items-center gap-2">
            {/* A saved insight name can be hundreds of characters, so it truncates instead of pushing
                the controls out of a narrow card. The full name stays available on hover. */}
            <div
                className="truncate text-xs font-semibold uppercase tracking-wider text-muted-foreground"
                title={title}
            >
                {title}
            </div>
            {children && <div className="ml-auto flex shrink-0 items-center gap-2">{children}</div>}
        </div>
    )
}
