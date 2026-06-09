import type { ReactElement, ReactNode } from 'react'

// Fixed pixel size, not width:100% — the chart sizes its canvas off a ResizeObserver, which measures
// 0 for a percentage width at mount in the headless snapshot runner and draws nothing.
export function ChartDemoFrame({
    children,
    width = 640,
    height = 320,
}: {
    children: ReactNode
    width?: number
    height?: number
}): ReactElement {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'flex', flexDirection: 'column', width, height }}>{children}</div>
    )
}
