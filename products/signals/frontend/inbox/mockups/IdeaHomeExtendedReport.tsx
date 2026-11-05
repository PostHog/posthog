import { TodaySectionTitle } from 'scenes/project-homepage/today/TodaySectionTitle'

import { MockDisclosure } from './MockDisclosure'
import { MockPullRequestFiles } from './MockPullRequestFiles'
import { MockReportNav } from './MockReportNav'
import { MockSinglePageReport } from './MockSinglePageReport'
import { MockTimeList } from './MockTimeList'
import { MockTrend } from './MockTrend'
import { LEAD_REPORT, OPEN_REPORTS } from './mockupData'
import { checksSummary, pullRequestLine } from './mockupFormat'
import { MockupPage } from './MockupPage'

export function IdeaHomeExtendedReport(): JSX.Element {
    const report = LEAD_REPORT
    const pullRequest = report.pullRequest
    return (
        <MockupPage>
            <MockReportNav position={1} total={OPEN_REPORTS.length} />
            <MockSinglePageReport report={report}>
                <section className="flex flex-col gap-1" aria-label="Details">
                    <TodaySectionTitle>Details</TodaySectionTitle>
                    <div className="InboxMockup__disclosures">
                        {pullRequest && (
                            <MockDisclosure
                                title="Pull request"
                                summary={`${pullRequestLine(pullRequest)} · ${checksSummary(pullRequest)}`}
                            >
                                <MockPullRequestFiles pullRequest={pullRequest} />
                            </MockDisclosure>
                        )}
                        {report.trend && (
                            <MockDisclosure title="Impact" summary={report.trend.value}>
                                <div className="flex flex-col gap-2">
                                    <MockTrend trend={report.trend} />
                                    <p className="InboxMockup__muted">{report.impact}</p>
                                </div>
                            </MockDisclosure>
                        )}
                        <MockDisclosure title="Reviewers" summary={report.reviewers.join(', ') || 'None yet'}>
                            <MockTimeList
                                items={report.reviewers.map((name, index) => ({
                                    key: name,
                                    text: name,
                                    trailing: index === 0 ? 'Owns checkout code' : 'Changed these files last',
                                }))}
                            />
                        </MockDisclosure>
                        <MockDisclosure
                            title="Agent runs"
                            summary={`${report.runs.length} runs · ${report.spend} spent`}
                        >
                            <MockTimeList
                                items={report.runs.map((run) => ({
                                    key: run.when,
                                    text: run.label,
                                    trailing: `${run.when} · ${run.cost}`,
                                }))}
                            />
                        </MockDisclosure>
                        <MockDisclosure title="Activity" summary={`${report.activity.length} events`}>
                            <MockTimeList
                                items={report.activity.map((item) => ({
                                    key: item.when,
                                    text: item.text,
                                    trailing: item.when,
                                }))}
                            />
                        </MockDisclosure>
                    </div>
                </section>
            </MockSinglePageReport>
        </MockupPage>
    )
}
