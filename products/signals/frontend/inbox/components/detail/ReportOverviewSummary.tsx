import { Fragment, ReactNode, useMemo } from 'react'

import { IconDocument } from '@posthog/icons'

import { ChartPlacements } from '../../utils/chartPlacement'
import { parseReportSummary, ReportSummarySectionKind } from '../../utils/reportSummary'
import { DetailSection } from './DetailSection'
import { ReportSummaryMarkdown } from './ReportSummaryMarkdown'

const READING_ORDER: ReportSummarySectionKind[] = ['problem', 'impact', 'expected-impact', 'solution']

export function ReportOverviewSummary({
    summary,
    chartPlacements,
    observation,
    impactMetrics,
    expectedImpact,
    nextAction,
    onToggleAnalysis,
}: {
    summary: string
    chartPlacements: ChartPlacements
    observation?: ReactNode
    impactMetrics?: ReactNode
    expectedImpact?: ReactNode
    nextAction?: ReactNode
    onToggleAnalysis: (collapsed: boolean) => void
}): JSX.Element {
    const parsed = useMemo(() => parseReportSummary(summary), [summary])
    const hasOverview = parsed.sections.some(
        (section) => section.kind === 'problem' || (parsed.lead && section.kind !== 'other')
    )
    // Unstructured reports stay whole. An unknown heading can contain the report's only finding.
    const overview = hasOverview
        ? READING_ORDER.flatMap((kind) => parsed.sections.filter((section) => section.kind === kind))
        : parsed.sections
    const analysis = hasOverview ? parsed.sections.filter((section) => section.kind === 'other') : []
    const impactFallback = !overview.some((section) => section.kind === 'impact') && impactMetrics
    const expectedImpactFallback = !overview.some((section) => section.kind === 'expected-impact') && expectedImpact
    const solutionIndex = overview.findIndex((section) => section.kind === 'solution')

    return (
        <div className="flex flex-col gap-6">
            {parsed.lead && (
                <ReportSummaryMarkdown
                    markdown={parsed.lead}
                    sourceOffset={parsed.leadOffset}
                    chartPlacements={chartPlacements}
                    className="text-base text-primary leading-relaxed break-words [&>*+*]:mt-3.5"
                />
            )}
            {observation}
            {overview.map((section, index) => (
                <Fragment key={section.bodyOffset}>
                    {index === solutionIndex && impactFallback}
                    {index === solutionIndex && expectedImpactFallback}
                    <section className="flex flex-col gap-2">
                        <h2 className="m-0 text-lg font-semibold">{section.heading}</h2>
                        {section.kind === 'impact' && impactMetrics}
                        <ReportSummaryMarkdown
                            markdown={section.body}
                            sourceOffset={section.bodyOffset}
                            chartPlacements={chartPlacements}
                        />
                        {section.kind === 'expected-impact' && expectedImpact}
                    </section>
                </Fragment>
            ))}
            {solutionIndex === -1 && impactFallback}
            {solutionIndex === -1 && expectedImpactFallback}
            {nextAction && (
                <section className="flex flex-col gap-3">
                    <h2 className="m-0 text-lg font-semibold">Next step</h2>
                    {nextAction}
                </section>
            )}
            {analysis.length > 0 && (
                <DetailSection
                    icon={<IconDocument />}
                    title="Full analysis"
                    summary={analysis.map((section) => section.heading).join(' · ')}
                    collapsible
                    defaultCollapsed
                    onToggleCollapsed={onToggleAnalysis}
                >
                    <div className="flex flex-col gap-6">
                        {analysis.map((section) => (
                            <section key={section.bodyOffset} className="flex flex-col gap-2">
                                <h2 className="m-0 text-lg font-semibold">{section.heading}</h2>
                                <ReportSummaryMarkdown
                                    markdown={section.body}
                                    sourceOffset={section.bodyOffset}
                                    chartPlacements={chartPlacements}
                                />
                            </section>
                        ))}
                    </div>
                </DetailSection>
            )}
        </div>
    )
}
