import { LemonCard, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import type { AEOWeeklyReportApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotPromptKpiCard } from './ContentAutopilotPromptKpiCard'
import {
    WEEKLY_REPORT_PAGE_ROLE_LABELS,
    formatWeeklyChange,
    formatWeeklyRate,
    weeklyChangeStatus,
    weeklyKpi,
    weeklyPageLabel,
    weeklyReportPeriod,
    weeklyTopicName,
} from './weeklyReport'

/** The weekly AI visibility report as a subscription sends it, rendered from the same endpoint. */
export const ContentAutopilotWeeklyReportPreview = ({ report }: { report: AEOWeeklyReportApi }): JSX.Element => {
    const { scorecard } = report
    return (
        <div className="flex flex-col gap-4" data-attr="content-autopilot-weekly-report-preview">
            <p className="m-0 text-secondary">
                Brand visibility in AI answers to non-branded prompts, {weeklyReportPeriod(report)}, compared with the
                week before. Based on {scorecard.answers.toLocaleString()}{' '}
                {scorecard.answers === 1 ? 'answer' : 'answers'}.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <ContentAutopilotPromptKpiCard
                    label="Brand visibility"
                    description="Share of answers that name your brand or cite your site."
                    {...weeklyKpi(scorecard.visibility, scorecard.previous_visibility, scorecard.visibility_change)}
                />
                <ContentAutopilotPromptKpiCard
                    label="Citation rate"
                    description="Share of answers that link to a page on your site as a source."
                    {...weeklyKpi(
                        scorecard.citation_rate,
                        scorecard.previous_citation_rate,
                        scorecard.citation_rate_change
                    )}
                />
            </div>

            <section className="flex flex-col gap-2">
                <h4 className="m-0">Topics</h4>
                <LemonTable
                    size="small"
                    dataSource={report.topics}
                    rowKey="topic"
                    emptyState="No topic had answers this week."
                    columns={[
                        {
                            title: 'Topic',
                            key: 'topic',
                            render: (_, row) => (
                                <span className={row.topic ? 'font-semibold' : 'font-semibold text-muted'}>
                                    {weeklyTopicName(row.topic)}
                                </span>
                            ),
                        },
                        {
                            title: 'Visibility',
                            key: 'visibility',
                            align: 'right',
                            render: (_, row) => (
                                <span className="tabular-nums">{formatWeeklyRate(row.visibility)}</span>
                            ),
                        },
                        {
                            title: 'Change',
                            key: 'visibility_change',
                            align: 'right',
                            render: (_, row) => (
                                <LemonTag type={weeklyChangeStatus(row.visibility_change)} className="tabular-nums">
                                    {formatWeeklyChange(row.visibility_change)}
                                </LemonTag>
                            ),
                        },
                        {
                            title: 'Answers',
                            key: 'answers',
                            align: 'right',
                            render: (_, row) => <span className="tabular-nums">{row.answers.toLocaleString()}</span>,
                        },
                    ]}
                />
            </section>

            <section className="flex flex-col gap-2">
                <h4 className="m-0">Pages to watch</h4>
                {report.pages.length ? (
                    <ul className="m-0 p-0 list-none flex flex-col gap-2">
                        {report.pages.map((page) => (
                            <li key={page.role}>
                                <LemonCard hoverEffect={false} className="p-3 flex flex-col gap-1">
                                    <span className="text-muted text-xs font-semibold uppercase">
                                        {WEEKLY_REPORT_PAGE_ROLE_LABELS[page.role]}
                                    </span>
                                    <Link to={page.url} target="_blank" className="font-semibold break-all">
                                        {weeklyPageLabel(page.url)}
                                    </Link>
                                    <span className="text-secondary text-sm">
                                        Cited in {formatWeeklyRate(page.citation_rate)} of answers in{' '}
                                        {weeklyTopicName(page.topic)}{' '}
                                        <LemonTag type={weeklyChangeStatus(page.change)} className="tabular-nums">
                                            {formatWeeklyChange(page.change)}
                                        </LemonTag>
                                    </span>
                                </LemonCard>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p className="m-0 text-muted">No page's citation rate moved within a topic this week.</p>
                )}
            </section>

            <section className="flex flex-col gap-2">
                <h4 className="m-0">Suggested actions</h4>
                {report.actions.length ? (
                    <ol className="m-0 pl-5 list-decimal flex flex-col gap-1">
                        {report.actions.map((action) => (
                            <li key={action.kind + action.topic + (action.page_url ?? '')}>{action.text}</li>
                        ))}
                    </ol>
                ) : (
                    <p className="m-0 text-muted">No changes this week were large enough to act on.</p>
                )}
            </section>
        </div>
    )
}
