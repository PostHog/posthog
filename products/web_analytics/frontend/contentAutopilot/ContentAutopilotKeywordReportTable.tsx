import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonTable, LemonTableColumn } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import type { AEOKeywordReportRowApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { KEYWORDS_DAYS } from './keywordsReport'

type ReportColumn = LemonTableColumn<AEOKeywordReportRowApi, keyof AEOKeywordReportRowApi | undefined>

const Rate = ({ value, of }: { value: number | null; of?: number }): JSX.Element =>
    value === null ? (
        <span className="text-muted">-</span>
    ) : (
        <span className="tabular-nums">
            {percentage(value, 0)}
            {of !== undefined ? <span className="text-muted"> of {of}</span> : null}
        </span>
    )

const byRate =
    (field: keyof AEOKeywordReportRowApi) =>
    (a: AEOKeywordReportRowApi, b: AEOKeywordReportRowApi): number =>
        ((a[field] as number | null) ?? -1) - ((b[field] as number | null) ?? -1)

const COLUMNS: ReportColumn[] = [
    {
        title: 'Keyword',
        key: 'keyword',
        render: (_, row) => <span className="font-semibold">{row.keyword}</span>,
        sorter: (a, b) => a.keyword.localeCompare(b.keyword),
    },
    {
        title: 'Mention rate',
        key: 'answer_mention_rate',
        align: 'right',
        tooltip: 'Of the answers that use this keyword, the share that name your brand or cite your site.',
        sorter: byRate('answer_mention_rate'),
        render: (_, row) => <Rate value={row.answer_mention_rate} of={row.answer_checks} />,
    },
    {
        title: 'Searched',
        key: 'searched_rate',
        align: 'right',
        tooltip: 'Share of all answers where the engine searched the web for this keyword.',
        sorter: byRate('searched_rate'),
        render: (_, row) => <Rate value={row.searched_rate} />,
    },
    {
        title: 'Cited when searched',
        key: 'searched_cited_rate',
        align: 'right',
        tooltip: 'Of the answers whose searches used this keyword, the share that cite your site.',
        sorter: byRate('searched_cited_rate'),
        render: (_, row) => <Rate value={row.searched_cited_rate} of={row.searched_checks} />,
    },
    {
        title: 'Uses per answer',
        key: 'uses_per_answer',
        align: 'right',
        tooltip: 'How many times the answers that use this keyword repeat it, on average.',
        sorter: byRate('uses_per_answer'),
        render: (_, row) =>
            row.uses_per_answer === null ? (
                <span className="text-muted">-</span>
            ) : (
                <span className="tabular-nums">{row.uses_per_answer.toFixed(1)}</span>
            ),
    },
    {
        title: 'In prompts',
        key: 'prompts',
        align: 'right',
        tooltip: 'Prompts whose text contains this keyword, and how often their answers cite your site.',
        sorter: (a, b) => a.prompts - b.prompts,
        render: (_, row) =>
            row.prompts ? (
                <span className="tabular-nums">
                    {pluralize(row.prompts, 'prompt')}
                    <span className="text-muted">, {percentage(row.prompt_cited_rate ?? 0, 0)} cited</span>
                </span>
            ) : (
                <span className="text-muted">-</span>
            ),
    },
    {
        title: 'Position',
        key: 'avg_citation_position',
        align: 'right',
        tooltip:
            'Where your site appears among the cited sources, on average, in answers that use this keyword and cite you. 1 is first.',
        sorter: byRate('avg_citation_position'),
        render: (_, row) =>
            row.avg_citation_position === null ? (
                <span className="text-muted">-</span>
            ) : (
                <span className="tabular-nums">{row.avg_citation_position.toFixed(1)}</span>
            ),
    },
    {
        title: 'First mention',
        key: 'median_first_mention_depth',
        align: 'right',
        tooltip:
            'How far into the answer your brand is first named, as a share of its length. 0% is the first sentence. Median over the answers that use this keyword and name your brand.',
        sorter: byRate('median_first_mention_depth'),
        render: (_, row) => <Rate value={row.median_first_mention_depth} />,
    },
]

export const ContentAutopilotKeywordReportTable = (): JSX.Element => {
    const { report, reportLoading, reportError } = useValues(contentAutopilotKeywordsLogic)
    const { loadReport } = useActions(contentAutopilotKeywordsLogic)

    return (
        <PagePerformanceCard className="min-w-0">
            <PagePerformanceCardHeader title="How your keywords perform" />
            {reportError ? (
                <LemonBanner
                    type="error"
                    className="m-3"
                    action={{ children: 'Try again', onClick: loadReport, loading: reportLoading }}
                >
                    Couldn't load the keyword report. Try again, and if it keeps happening contact support.
                </LemonBanner>
            ) : !report ? (
                <LemonSkeleton className="h-32 m-3" />
            ) : report.answers === 0 ? (
                <p className="m-0 p-3 text-muted" data-attr="content-autopilot-keywords-report-empty">
                    No answers in the last {KEYWORDS_DAYS} days. Once the daily run checks your prompts, this table
                    shows how each keyword performs.
                </p>
            ) : (
                <div className="overflow-x-auto" data-attr="content-autopilot-keywords-report">
                    <LemonTable<AEOKeywordReportRowApi>
                        size="small"
                        embedded
                        dataSource={report.keywords}
                        rowKey="keyword"
                        loading={reportLoading}
                        columns={COLUMNS}
                        defaultSorting={{ columnKey: 'answer_mention_rate', order: -1 }}
                        footer={
                            <span className="px-3 py-2 text-xs text-muted">
                                Over {pluralize(report.answers, 'answer')} in the last {KEYWORDS_DAYS} days. A keyword
                                matches any text that contains it, case ignored.
                            </span>
                        }
                    />
                </div>
            )}
        </PagePerformanceCard>
    )
}
