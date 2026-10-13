import { ReactNode, useCallback } from 'react'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { ChartPlacements } from '../../utils/chartPlacement'
import { ReportChart } from './ReportChart'

const PROSE_CLASS =
    'text-[15px] text-secondary leading-relaxed break-words [&>*+*]:mt-3.5 [&_[data-attr=report-chart]]:my-5 [&_li]:my-1 [&_ul]:my-2 [&_ol]:my-2 [&_h1]:mt-8 [&_h1]:text-lg [&_h2]:mt-8 [&_h2]:text-lg [&_h3]:mt-6 [&_h3]:text-base'

interface ReportSummaryMarkdownProps {
    markdown: string
    /** Where `markdown` starts in the full summary; chart placements are keyed on the full summary. */
    sourceOffset: number
    chartPlacements: ChartPlacements
    className?: string
}

/** One slice of the summary. Owns its chart-ref callback so `LemonMarkdown` keeps its anchor component. */
export function ReportSummaryMarkdown({
    markdown,
    sourceOffset,
    chartPlacements,
    className,
}: ReportSummaryMarkdownProps): JSX.Element {
    // Depends on placement alone. `LemonMarkdown` memoizes its anchor component on this callback, so
    // anything else in here would rebuild that component as the report polls and unmount every chart.
    const renderChartRef = useCallback(
        (chartId: string, offset?: number): ReactNode =>
            offset !== undefined && chartPlacements.inlineByOffset.get(sourceOffset + offset) === chartId ? (
                <ReportChart chartId={chartId} />
            ) : null,
        [chartPlacements, sourceOffset]
    )
    return (
        <LemonMarkdown className={className ?? PROSE_CLASS} disableImages renderChartRef={renderChartRef}>
            {markdown}
        </LemonMarkdown>
    )
}
