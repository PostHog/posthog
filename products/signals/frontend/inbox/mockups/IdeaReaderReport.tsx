import { type MockFact, MockFactList } from './MockFactList'
import { MockReportNav } from './MockReportNav'
import { MockSinglePageReport } from './MockSinglePageReport'
import { LEAD_REPORT, OPEN_REPORTS } from './mockupData'
import { checksSummary } from './mockupFormat'
import { MockupPage } from './MockupPage'

export function IdeaReaderReport(): JSX.Element {
    const report = LEAD_REPORT
    const pullRequest = report.pullRequest
    const facts: MockFact[] = [
        { term: 'Status', value: report.stateLabel ?? 'Open' },
        { term: 'Owner', value: report.owner },
        ...(pullRequest
            ? [
                  { term: 'Pull request', value: `#${pullRequest.number}` },
                  {
                      term: 'Checks',
                      value: (
                          <span className={pullRequest.checks.failed > 0 ? 'InboxMockup__risk' : undefined}>
                              {checksSummary(pullRequest)}
                          </span>
                      ),
                  },
              ]
            : []),
        { term: 'Reviewers', value: report.reviewers.join(', ') || 'None yet' },
        { term: 'Agent runs', value: `${report.runs.length} runs, ${report.spend}` },
        { term: 'Sources', value: report.sources },
        { term: 'Last activity', value: report.activity[report.activity.length - 1]?.text ?? 'None' },
    ]
    return (
        <MockupPage width="wide">
            <MockReportNav position={1} total={OPEN_REPORTS.length} />
            <div className="InboxMockup__withRail">
                <div className="InboxMockup__railMain">
                    <MockSinglePageReport report={report} />
                </div>
                <aside className="InboxMockup__rail" aria-label="Report facts">
                    <MockFactList facts={facts} />
                </aside>
            </div>
        </MockupPage>
    )
}
