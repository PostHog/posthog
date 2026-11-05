import { Heading, Text } from '@posthog/quill'

import { TodaySectionTitle } from 'scenes/project-homepage/today/TodaySectionTitle'

import { MockEvidenceList } from './MockEvidenceList'
import { MockFeedback } from './MockFeedback'
import { MockNextStep } from './MockNextStep'
import { MockPullRequestFiles } from './MockPullRequestFiles'
import { MockReportMeta } from './MockReportMeta'
import { MockReportNav } from './MockReportNav'
import { MockTimelineStep } from './MockTimelineStep'
import { MockTimeList } from './MockTimeList'
import { MockTrend } from './MockTrend'
import { LEAD_REPORT, OPEN_REPORTS } from './mockupData'
import { checksSummary, pullRequestLine } from './mockupFormat'
import { MockupPage } from './MockupPage'
import { MockVerdictButtons } from './MockVerdictButtons'

export function IdeaStagesReport(): JSX.Element {
    const report = LEAD_REPORT
    const pullRequest = report.pullRequest
    return (
        <MockupPage>
            <MockReportNav position={1} total={OPEN_REPORTS.length} />
            <article className="TodayReportArticle flex flex-col gap-10">
                <header className="flex flex-col gap-3">
                    <MockReportMeta report={report} actions={<MockVerdictButtons labelled />} />
                    <div className="flex flex-col gap-2">
                        <Heading size="xl" render={<h1 />} className="leading-snug text-balance">
                            {report.title}
                        </Heading>
                        <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                            {report.abstract}
                        </Text>
                    </div>
                </header>
                <section className="flex flex-col gap-3" aria-label="Progress">
                    <TodaySectionTitle>Progress</TodaySectionTitle>
                    <ol className="InboxMockup__timeline">
                        <MockTimelineStep
                            title="Signal found"
                            summary={`${report.evidenceCount} signals from ${report.sources}`}
                            when="Mon 09:02"
                            state="done"
                        >
                            <MockEvidenceList report={report} />
                        </MockTimelineStep>
                        <MockTimelineStep title="Proposal" summary={report.proposal} when="Mon 09:40" state="done">
                            <div className="flex flex-col gap-2">
                                <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                                    {report.whatHappened}
                                </Text>
                                <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                                    {report.proposal}
                                </Text>
                            </div>
                        </MockTimelineStep>
                        {pullRequest && (
                            <MockTimelineStep
                                title="Pull request"
                                summary={pullRequestLine(pullRequest)}
                                when="Mon 10:40"
                                state="done"
                            >
                                <div className="flex flex-col gap-4">
                                    <MockPullRequestFiles pullRequest={pullRequest} />
                                    <MockTimeList
                                        items={report.runs.map((run) => ({
                                            key: run.when,
                                            text: run.label,
                                            trailing: `${run.when} · ${run.cost}`,
                                        }))}
                                    />
                                </div>
                            </MockTimelineStep>
                        )}
                        {pullRequest && (
                            <MockTimelineStep
                                title="Checks"
                                summary={checksSummary(pullRequest)}
                                when="Tue 08:20"
                                state="done"
                            />
                        )}
                        <MockTimelineStep
                            title="Review"
                            summary={`Waits for ${report.reviewers.join(' or ')}`}
                            state="current"
                        >
                            <MockNextStep report={report} />
                        </MockTimelineStep>
                        <MockTimelineStep title="Merged" summary="After the review" state="next" />
                        {report.trend && (
                            <MockTimelineStep title="Impact" summary="Watched for 7 days after the merge" state="next">
                                <div className="flex flex-col gap-2">
                                    <MockTrend trend={report.trend} />
                                    <p className="InboxMockup__muted">{report.impact}</p>
                                </div>
                            </MockTimelineStep>
                        )}
                    </ol>
                </section>
                <MockFeedback />
            </article>
        </MockupPage>
    )
}
