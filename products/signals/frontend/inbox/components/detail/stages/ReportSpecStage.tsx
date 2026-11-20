import { ReactNode } from 'react'

import { IconCompass, IconDocument } from '@posthog/icons'
import { Skeleton, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { SignalNode } from 'scenes/debug/signals/types'

import { SignalReport } from '../../../types'
import { parseReportSummary, ReportSummarySectionKind } from '../../../utils/reportSummary'
import { prettifyScoutSkillName } from '../../../utils/scoutRunsWindow'
import { ReportEvidenceRow } from './ReportEvidenceRow'
import { ReportImpactCards } from './ReportImpactCards'
import { ReportStageDetails } from './ReportStageDetails'
import { ReportStageProse } from './ReportStageProse'
import { ReportStageSectionTitle } from './ReportStageSectionTitle'

/** What is wrong and why it matters: the problem, the figures that size it, and the evidence behind it. */
export function ReportSpecStage({
    report,
    signals,
    children,
}: {
    report: SignalReport
    /** Null while the evidence loads. */
    signals: SignalNode[] | null
    /** The detail lines of this stage. */
    children?: ReactNode
}): JSX.Element {
    const summary = parseReportSummary(report.summary)
    const sectionBody = (kind: ReportSummarySectionKind): string | null =>
        summary.sections.find((section) => section.kind === kind)?.body ?? null
    const problem = sectionBody('problem')
    const impact = sectionBody('impact')
    const primaryMetric = report.metrics?.find((metric) => metric.role === 'primary') ?? null
    const evidence = [...(signals ?? [])].sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp))
    const firstEvidenceAt = evidence.length > 0 ? evidence[evidence.length - 1].timestamp : null

    return (
        <div className="flex flex-col gap-8">
            <section className="flex flex-col gap-3" aria-label="Problem">
                <ReportStageSectionTitle>Problem</ReportStageSectionTitle>
                {/* The lead is under the title on every stage, so the problem does not repeat it. */}
                {problem || summary.lead ? (
                    <ReportStageProse markdown={problem ?? summary.lead ?? ''} />
                ) : (
                    <Text size="sm" variant="muted" render={<p className="m-0" />}>
                        No summary yet. An agent is still investigating.
                    </Text>
                )}
                <Text
                    size="xs"
                    variant="muted"
                    render={<div />}
                    className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono"
                >
                    {report.scout_name && (
                        <span className="flex items-center gap-1.5">
                            <IconCompass aria-hidden className="size-3.5" />
                            <span>{`Scout: ${prettifyScoutSkillName(report.scout_name)}`}</span>
                        </span>
                    )}
                    {firstEvidenceAt && (
                        <span className="flex items-center gap-1.5">
                            <IconDocument aria-hidden className="size-3.5" />
                            <span>Evidence found on</span>
                            <TZLabel time={firstEvidenceAt}>
                                <span>{dayjs(firstEvidenceAt).format('dddd, MMM D, YYYY')}</span>
                            </TZLabel>
                        </span>
                    )}
                </Text>
            </section>

            {primaryMetric && (
                <ReportImpactCards metric={primaryMetric} expectedImpact={sectionBody('expected-impact')} />
            )}

            {impact && (
                <section className="flex flex-col gap-3" aria-label="Impact">
                    <ReportStageSectionTitle>Impact</ReportStageSectionTitle>
                    <ReportStageProse markdown={impact} />
                </section>
            )}

            <section className="flex flex-col gap-1" aria-label="Evidence" data-attr="inbox-report-evidence">
                <div className="flex items-baseline gap-2">
                    <ReportStageSectionTitle>Evidence</ReportStageSectionTitle>
                    <Text size="sm" variant="muted" render={<span />} className="tabular-nums">
                        {String(report.signal_count)}
                    </Text>
                </div>
                {signals === null ? (
                    <div className="flex flex-col gap-2 py-2" aria-busy>
                        <Skeleton className="h-3.5 w-full" />
                        <Skeleton className="h-3.5 w-2/3" />
                    </div>
                ) : evidence.length === 0 ? (
                    <Text size="sm" variant="muted" render={<p className="m-0" />}>
                        No signals are attached to this report yet.
                    </Text>
                ) : (
                    <div className="-mx-2 flex flex-col">
                        {evidence.map((signal) => (
                            <ReportEvidenceRow key={signal.signal_id} signal={signal} />
                        ))}
                    </div>
                )}
            </section>
            <ReportStageDetails>{children}</ReportStageDetails>
        </div>
    )
}
