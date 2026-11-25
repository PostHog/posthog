import { useActions, useValues } from 'kea'

import { IconInfo, IconPencil } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonSkeleton,
    LemonTable,
    LemonTableColumn,
    LemonTableColumnGroup,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import type { AEOKeywordReportRowApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { GOOGLE_SEARCH_CONSOLE_DOCS_URL } from '../searchAndAi/searchAndAiQueries'
import { contentAutopilotKeywordSearchLogic } from './contentAutopilotKeywordSearchLogic'
import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { ContentAutopilotKeywordSuggestButton } from './ContentAutopilotKeywordSuggestButton'
import type { KeywordSearchImpressions } from './keywordSearchImpressions'
import { windowRange } from './utils'

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

const KEYWORD_COLUMN: ReportColumn = {
    title: 'Keyword',
    key: 'keyword',
    render: (_, row) => <span className="font-semibold">{row.keyword}</span>,
    sorter: (a, b) => a.keyword.localeCompare(b.keyword),
}

const AI_COLUMNS: ReportColumn[] = [
    {
        title: 'Visibility',
        key: 'answer_mention_rate',
        align: 'right',
        tooltip: 'Share of answers containing this keyword that name your brand or link to your site.',
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

type SearchMetric = keyof KeywordSearchImpressions

const GroupTitle = ({ title, description }: { title: string; description: string }): JSX.Element => (
    <span className="inline-flex items-center gap-1">
        {title}
        <Tooltip title={description} interactive openOnClick>
            <LemonButton size="xsmall" noPadding icon={<IconInfo />} aria-label={`About ${title}`} />
        </Tooltip>
    </span>
)

const SEARCH_COLUMNS: { metric: SearchMetric; title: string; tooltip: string }[] = [
    {
        metric: 'impressions',
        title: 'Impressions',
        tooltip:
            'How often your site appeared on Google for searches that contain this keyword, in this date range. It comes from Google Search Console and counts searches where your site was shown, not every search for the keyword.',
    },
    {
        metric: 'clicks',
        title: 'Clicks',
        tooltip: 'Clicks to your site from Google searches that contain this keyword, in this date range.',
    },
    {
        metric: 'searches',
        title: 'Searches',
        tooltip: 'Different Google searches that contain this keyword and showed your site, in this date range.',
    },
    {
        metric: 'position',
        title: 'Search position',
        tooltip:
            'Where your top result ranks on Google for searches that contain this keyword, on average, weighted by impressions. 1 is first.',
    },
]

/** One sortable column per Search Console number. Null `impressions` means they are loading. */
const searchColumns = (impressions: Record<string, KeywordSearchImpressions> | null): ReportColumn[] =>
    SEARCH_COLUMNS.map(({ metric, title, tooltip }) => ({
        title,
        key: `google_${metric}`,
        align: 'right',
        tooltip,
        // A keyword with no number sorts as the lowest count, and as the worst position.
        sorter: (a, b) => {
            const missing = metric === 'position' ? Infinity : 0
            return (impressions?.[a.keyword]?.[metric] ?? missing) - (impressions?.[b.keyword]?.[metric] ?? missing)
        },
        render: (_, row) => {
            if (!impressions) {
                return <LemonSkeleton className="ml-auto h-4 w-12" />
            }
            const value = impressions[row.keyword]?.[metric] ?? null
            if (metric === 'position') {
                return value === null ? (
                    <span className="text-muted">-</span>
                ) : (
                    <span className="tabular-nums">{value.toFixed(1)}</span>
                )
            }
            return <span className="tabular-nums">{humanFriendlyNumber(value ?? 0, 0)}</span>
        },
    }))

export const ContentAutopilotKeywordReportTable = (): JSX.Element => {
    const { report, reportLoading, reportError } = useValues(contentAutopilotKeywordsLogic)
    const { loadReport } = useActions(contentAutopilotKeywordsLogic)
    const { searchTable, searchConsoleMissing, impressions, impressionsLoading, impressionsFailed } = useValues(
        contentAutopilotKeywordSearchLogic
    )
    const { openKeywordsModal } = useActions(contentAutopilotKeywordsLogic)
    const columns: LemonTableColumnGroup<AEOKeywordReportRowApi>[] = [
        { children: [KEYWORD_COLUMN] },
        {
            title: (
                <GroupTitle
                    title="AI answers"
                    description="An answer or search counts for a keyword when its text contains the keyword."
                />
            ),
            children: AI_COLUMNS,
        },
        // The columns show only for a project with a Search Console source whose numbers loaded or are loading.
        ...(searchTable && !impressionsFailed
            ? [
                  {
                      title: <GroupTitle title="Google search" description="From Google Search Console." />,
                      children: searchColumns(impressionsLoading ? null : impressions),
                  },
              ]
            : []),
    ]

    return (
        <PagePerformanceCard className="min-w-0">
            <PagePerformanceCardHeader
                title="How your keywords perform"
                actions={
                    <div className="flex flex-wrap items-center gap-2">
                        <ContentAutopilotKeywordSuggestButton size="small" />
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPencil />}
                            onClick={openKeywordsModal}
                            data-attr="content-autopilot-keywords-manage"
                        >
                            Manage keywords
                        </LemonButton>
                    </div>
                }
            />
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
                    No answers {windowRange(report)}. Once the daily run checks your prompts, this table shows how each
                    keyword performs.
                </p>
            ) : (
                <div className="overflow-x-auto" data-attr="content-autopilot-keywords-report">
                    <LemonTable<AEOKeywordReportRowApi>
                        size="small"
                        embedded
                        dataSource={report.keywords}
                        rowKey="keyword"
                        loading={reportLoading}
                        columns={columns}
                        defaultSorting={{ columnKey: 'answer_mention_rate', order: -1 }}
                        footer={
                            searchConsoleMissing ? (
                                <span className="px-3 py-2 text-xs text-muted">
                                    <Link to={GOOGLE_SEARCH_CONSOLE_DOCS_URL} target="_blank">
                                        Connect Google Search Console
                                    </Link>{' '}
                                    to see how often your site appears on Google for each keyword.
                                </span>
                            ) : impressionsFailed ? (
                                <span className="px-3 py-2 text-xs text-muted">
                                    Couldn't load the Search Console numbers. Reload the page to try again.
                                </span>
                            ) : undefined
                        }
                    />
                </div>
            )}
        </PagePerformanceCard>
    )
}
