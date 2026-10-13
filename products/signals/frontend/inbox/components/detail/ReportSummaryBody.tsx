import { Fragment, ReactNode, useMemo } from 'react'

import { ChartPlacements } from '../../utils/chartPlacement'
import { parseReportSummary } from '../../utils/reportSummary'
import { ReportSummaryMarkdown } from './ReportSummaryMarkdown'

interface ReportSummaryBodyProps {
    summary: string
    chartPlacements: ChartPlacements
    implementButton?: ReactNode
    /**
     * Says a pull request with the fix is open and links to it. Rendered under the Solution section, or after
     * the body when the summary has no sections, so a report never hides that its fix already shipped.
     */
    pullRequestNote?: ReactNode
    /**
     * The report's supporting metric tiles. Rendered at the top of the Impact section; a summary without one
     * gets an Impact section for them ahead of Solution, so the storyboard order holds.
     */
    impactMetrics?: ReactNode
    expectedImpact?: ReactNode
}

/**
 * The report summary as sections: the lead sentence, then Problem, Impact, and Solution under their
 * own headings. A summary without headings renders as one block of prose.
 */
export function ReportSummaryBody({
    summary,
    chartPlacements,
    implementButton,
    pullRequestNote,
    impactMetrics,
    expectedImpact,
}: ReportSummaryBodyProps): JSX.Element {
    const parsed = useMemo(() => parseReportSummary(summary), [summary])
    const hasSolutionSection = parsed.sections.some((section) => section.kind === 'solution')
    const hasImpactSection = parsed.sections.some((section) => section.kind === 'impact')
    const hasExpectedImpactSection = parsed.sections.some((section) => section.kind === 'expected-impact')
    const solutionIndex = parsed.sections.findIndex((section) => section.kind === 'solution')
    const impactFallback =
        impactMetrics && !hasImpactSection ? (
            <section className="flex flex-col gap-2">
                <h2 className="m-0 text-lg font-semibold">Impact</h2>
                {impactMetrics}
            </section>
        ) : null
    const expectedImpactFallback = expectedImpact && !hasExpectedImpactSection && (
        <section className="flex flex-col gap-2">
            <h2 className="m-0 text-lg font-semibold">Expected impact</h2>
            {expectedImpact}
        </section>
    )

    if (parsed.sections.length === 0) {
        return (
            <div className="flex flex-col gap-6">
                <ReportSummaryMarkdown
                    markdown={parsed.lead}
                    sourceOffset={parsed.leadOffset}
                    chartPlacements={chartPlacements}
                />
                {impactFallback}
                {expectedImpactFallback}
                {pullRequestNote}
            </div>
        )
    }

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
            {parsed.sections.map((section, index) => (
                <Fragment key={`${section.kind}-${section.bodyOffset}`}>
                    {index === solutionIndex && impactFallback}
                    {index === solutionIndex && expectedImpactFallback}
                    <section className="flex flex-col gap-2">
                        <h2 className="m-0 text-lg font-semibold">{section.heading}</h2>
                        {section.kind === 'impact' && impactMetrics && <div className="mb-1">{impactMetrics}</div>}
                        <ReportSummaryMarkdown
                            markdown={section.body}
                            sourceOffset={section.bodyOffset}
                            chartPlacements={chartPlacements}
                        />
                        {section.kind === 'expected-impact' && expectedImpact}
                        {section.kind === 'solution' && pullRequestNote && (
                            <div className="mt-2">{pullRequestNote}</div>
                        )}
                        {section.kind === 'solution' && implementButton && (
                            <div className="mt-2">{implementButton}</div>
                        )}
                    </section>
                </Fragment>
            ))}
            {!hasSolutionSection && impactFallback}
            {!hasSolutionSection && expectedImpactFallback}
            {!hasSolutionSection && pullRequestNote}
        </div>
    )
}
