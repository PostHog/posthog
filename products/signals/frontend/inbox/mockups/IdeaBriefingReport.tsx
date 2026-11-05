import { Heading, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { TodaySectionTitle } from 'scenes/project-homepage/today/TodaySectionTitle'
import { lowerFirst } from 'scenes/project-homepage/today/todaySignalReports'

import { MockEvidenceList } from './MockEvidenceList'
import { type MockFact, MockFactList } from './MockFactList'
import { MockFeedback } from './MockFeedback'
import { MockNextStep } from './MockNextStep'
import { MockReportMeta } from './MockReportMeta'
import { MockReportNav } from './MockReportNav'
import { MockTrend } from './MockTrend'
import { LEAD_REPORT, OPEN_REPORTS } from './mockupData'
import { checksSummary } from './mockupFormat'
import { MockupPage } from './MockupPage'
import { MockVerdictButtons } from './MockVerdictButtons'

function FootnoteMark({ reportId, number }: { reportId: string; number: number }): JSX.Element {
    return (
        <LinkPrimitive
            to={`#${reportId}-evidence-${number}`}
            disableClientSideRouting
            className="InboxMockup__footnoteMark"
        >
            {number}
        </LinkPrimitive>
    )
}

export function IdeaBriefingReport(): JSX.Element {
    const report = LEAD_REPORT
    const facts: MockFact[] = [
        { term: 'Priority', value: report.priority },
        { term: 'Owner', value: report.owner },
        { term: 'Sources', value: report.sources },
        ...(report.pullRequest
            ? [
                  { term: 'Pull request', value: `#${report.pullRequest.number}` },
                  { term: 'Checks', value: checksSummary(report.pullRequest) },
              ]
            : []),
        { term: 'Reviewers', value: report.reviewers.join(', ') || 'None yet' },
        { term: 'Agent spend', value: report.spend },
    ]
    return (
        <MockupPage width="wide">
            <MockReportNav position={1} total={OPEN_REPORTS.length} />
            <div className="InboxMockup__memo">
                <article className="InboxMockup__memoBody flex flex-col gap-8">
                    <header className="flex flex-col gap-3">
                        <MockReportMeta report={report} actions={<MockVerdictButtons labelled />} />
                        <Heading size="xl" render={<h1 />} className="leading-snug text-balance">
                            {report.title}
                        </Heading>
                        <p className="InboxMockup__dek">{report.abstract}</p>
                    </header>
                    <section className="flex flex-col gap-2">
                        <TodaySectionTitle>What happened</TodaySectionTitle>
                        <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                            {report.whatHappened}
                            <FootnoteMark reportId={report.id} number={1} />
                        </Text>
                        {report.trend && <MockTrend trend={report.trend} />}
                    </section>
                    <section className="flex flex-col gap-2">
                        <TodaySectionTitle>Why it matters</TodaySectionTitle>
                        <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                            {report.whyItMatters}
                            <FootnoteMark reportId={report.id} number={3} />
                        </Text>
                    </section>
                    <section className="flex flex-col gap-4">
                        <div className="flex flex-col gap-2">
                            <TodaySectionTitle>What we propose</TodaySectionTitle>
                            <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                                {report.proposal}
                            </Text>
                        </div>
                        <MockNextStep report={report} />
                    </section>
                    <section className="flex flex-col gap-2">
                        <TodaySectionTitle>What the agent did</TodaySectionTitle>
                        <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                            {report.runs
                                .map(
                                    (run, index) =>
                                        `${index === 0 ? 'On' : 'Then, on'} ${run.when}, it ${lowerFirst(run.label)}.`
                                )
                                .join(' ')}{' '}
                            {`The ${report.runs.length} runs cost ${report.spend}.`}
                        </Text>
                    </section>
                    <MockEvidenceList report={report} numbered />
                    <MockFeedback />
                </article>
                <aside className="InboxMockup__margin" aria-label="Report facts">
                    <MockFactList facts={facts} />
                </aside>
            </div>
        </MockupPage>
    )
}
