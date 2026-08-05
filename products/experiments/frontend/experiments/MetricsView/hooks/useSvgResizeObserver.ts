import { useEffect, useRef, useState } from 'react'

export interface SvgResizeObserverState {
    // Refs to attach to SVG elements for observation
    ticksSvgRef: React.RefObject<SVGSVGElement>
    chartSvgRef: React.RefObject<SVGSVGElement>

    // Height values for adjusting neighboring elements
    ticksSvgHeight: number
    chartSvgHeight: number
}

/**
 * Custom hook to observe SVG element resizing and manage heights for metrics charts
 *
 * This hook handles the dynamic height adjustments needed for experiment metric visualizations,
 * particularly managing the alignment between SVG charts and regular divs.
 *
 * @param deps - Optional array of dependencies to trigger re-observation
 * @returns Object containing refs and height values
 */
export function useSvgResizeObserver(deps: any[] = []): SvgResizeObserverState {
    const ticksSvgRef = useRef<SVGSVGElement>(null)
    const chartSvgRef = useRef<SVGSVGElement>(null)

    // Track SVG heights dynamically because we're fitting regular divs to match SVG viewports
    const [ticksSvgHeight, setTicksSvgHeight] = useState<number>(0)
    const [chartSvgHeight, setChartSvgHeight] = useState<number>(0)

    useEffect(() => {
        const ticksSvg = ticksSvgRef.current
        const chartSvg = chartSvgRef.current

        // oxlint-disable-next-line compat/compat
        const resizeObserver = new ResizeObserver((entries) => {
            for (const entry of entries) {
                if (entry.target === ticksSvg) {
                    setTicksSvgHeight(entry.contentRect.height)
                } else if (entry.target === chartSvg) {
                    setChartSvgHeight(entry.contentRect.height)
                }
            }
        })

        if (ticksSvg) {
            resizeObserver.observe(ticksSvg)
        }
        if (chartSvg) {
            resizeObserver.observe(chartSvg)
        }

        return () => {
            resizeObserver.disconnect()
        }
    }, deps)

    return {
        ticksSvgRef,
        chartSvgRef,
        ticksSvgHeight,
        chartSvgHeight,
    }
}
