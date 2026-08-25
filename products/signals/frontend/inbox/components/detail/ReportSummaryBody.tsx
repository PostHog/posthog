import { ReactNode, useCallback, useMemo } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { ChartPlacements } from '../../utils/chartPlacement'
import { parseReportSummary } from '../../utils/reportSummary'
import { ReportChart } from './ReportChart'
import { ReportDetailAction } from './ReportDetailActions'

const PROSE_CLASS =
    'text-[15px] text-secondary leading-relaxed break-words [&>*+*]:mt-3.5 [&_[data-attr=report-chart]]:my-5 [&_li]:my-1 [&_ul]:my-2 [&_ol]:my-2 [&_h1]:mt-8 [&_h1]:text-lg [&_h2]:mt-8 [&_h2]:text-lg [&_h3]:mt-6 [&_h3]:text-base'

interface SummaryMarkdownProps {
    markdown: string
    /** Where `markdown` starts in the full summary; chart placements are keyed on the full summary. */
    sourceOffset: number
    chartPlacements: ChartPlacements
    className?: string
}

/** One slice of the summary. Owns its chart-ref callback so `LemonMarkdown` keeps its anchor component. */
function SummaryMarkdown({ markdown, sourceOffset, chartPlacements, className }: SummaryMarkdownProps): JSX.Element {
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

interface ReportSummaryBodyProps {
    summary: string
    chartPlacements: ChartPlacements
    /** The Create PR action, rendered under the Solution section when the report offers it. */
    createPrAction?: ReportDetailAction
}

/**
 * The report summary as sections: the lead sentence, then Problem, Impact, and Solution under their
 * own headings. A summary without headings renders as one block of prose.
 */
export function ReportSummaryBody({ summary, chartPlacements, createPrAction }: ReportSummaryBodyProps): JSX.Element {
    const parsed = useMemo(() => parseReportSummary(summary), [summary])

    if (parsed.sections.length === 0) {
        return <SummaryMarkdown markdown={parsed.lead} sourceOffset={0} chartPlacements={chartPlacements} />
    }

    return (
        <div className="flex flex-col gap-6">
            {parsed.lead && (
                <SummaryMarkdown
                    markdown={parsed.lead}
                    sourceOffset={0}
                    chartPlacements={chartPlacements}
                    className="text-base text-primary leading-relaxed break-words [&>*+*]:mt-3.5"
                />
            )}
            {parsed.sections.map((section) => (
                <section key={`${section.kind}-${section.bodyOffset}`} className="flex flex-col gap-2">
                    <h2 className="m-0 text-lg font-semibold">{section.heading}</h2>
                    <SummaryMarkdown
                        markdown={section.body}
                        sourceOffset={section.bodyOffset}
                        chartPlacements={chartPlacements}
                    />
                    {section.kind === 'solution' && createPrAction && (
                        <div className="mt-2">
                            <LemonButton
                                type="primary"
                                size="small"
                                icon={createPrAction.icon}
                                loading={createPrAction.loading}
                                tooltip={createPrAction.disabledReason ? undefined : createPrAction.tooltip}
                                disabledReason={createPrAction.disabledReason}
                                onClick={createPrAction.onClick}
                                data-attr="inbox-report-solution-create-pr"
                            >
                                {createPrAction.label}
                            </LemonButton>
                        </div>
                    )}
                </section>
            ))}
        </div>
    )
}
