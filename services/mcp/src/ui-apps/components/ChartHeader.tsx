import type { ReactElement, ReactNode } from 'react'

interface ChartHeaderProps {
    title: string
    /** Right-aligned controls (chart-type select, options, …). Omit for visualizations with none. */
    children?: ReactNode
}

export function ChartHeader({ title, children }: ChartHeaderProps): ReactElement {
    return (
        <div className="mb-2 flex items-center gap-2">
            <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</div>
            {children && <div className="ml-auto flex items-center gap-2">{children}</div>}
        </div>
    )
}
