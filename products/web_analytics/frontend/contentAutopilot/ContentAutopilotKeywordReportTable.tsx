import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import type { LemonTableColumn, LemonTableColumnGroup } from '@posthog/lemon-ui'
import { Button, Skeleton, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { AEOKeywordReportRowApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { GOOGLE_SEARCH_CONSOLE_DOCS_URL } from '../searchAndAi/searchAndAiQueries'
import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilityCard } from './AiVisibilityCard'
import { AiVisibilityTable } from './AiVisibilityTable'
import { ContentAutopilotKeywordsActions } from './ContentAutopilotKeywordsActions'
import { contentAutopilotKeywordSearchLogic } from './contentAutopilotKeywordSearchLogic'
import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import type { KeywordSearchImpressions } from './keywordSearchImpressions'
import { windowRange } from './utils'

type ReportColumn = LemonTableColumn<AEOKeywordReportRowApi, keyof AEOKeywordReportRowApi | undefined>

const Rate = ({ value, of }: { value: number | null; of?: number }): JSX.Element =>
    value === null ? (
        <span className="text-muted-foreground">-</span>
    ) : (
        <span className="tabular-nums">
            {percentage(value, 0)}
            {of !== undefined ? <span className="text-muted-foreground"> of {of}</span> : null}
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
                <span className="text-muted-foreground">-</span>
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
                    <span className="text-muted-foreground">, {percentage(row.prompt_cited_rate ?? 0, 0)} cited</span>
                </span>
            ) : (
                <span className="text-muted-foreground">-</span>
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
                <span className="text-muted-foreground">-</span>
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
        <Tooltip>
            <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label={`About ${title}`} />}>
                <IconInfo />
            </TooltipTrigger>
            <TooltipContent className="max-w-80">{description}</TooltipContent>
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
                return <Skeleton className="ml-auto h-4 w-12" />
            }
            const value = impressions[row.keyword]?.[metric] ?? null
            if (metric === 'position') {
                return value === null ? (
                    <span className="text-muted-foreground">-</span>
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
    const { loadImpressions } = useActions(contentAutopilotKeywordSearchLogic)
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
        <AiVisibilityCard title="How your keywords perform" actions={<ContentAutopilotKeywordsActions />}>
            {reportError ? (
                <AiVisibilityBanner
                    type="error"
                    action={{ children: 'Try again', onClick: loadReport, loading: reportLoading }}
                >
                    Couldn't load the keyword report. Try again, and if it keeps happening contact support.
                </AiVisibilityBanner>
            ) : !report ? (
                <Skeleton className="h-32 w-full" />
            ) : report.answers === 0 ? (
                <Text
                    size="xs"
                    variant="muted"
                    render={<p className="m-0" />}
                    data-attr="content-autopilot-keywords-report-empty"
                >
                    No answers {windowRange(report)}. Once the daily run checks your prompts, this table shows how each
                    keyword performs.
                </Text>
            ) : (
                <div className="overflow-x-auto" data-attr="content-autopilot-keywords-report">
                    <AiVisibilityTable<AEOKeywordReportRowApi>
                        size="small"
                        embedded
                        dataSource={report.keywords}
                        rowKey="keyword"
                        loading={reportLoading}
                        columns={columns}
                        defaultSorting={{ columnKey: 'answer_mention_rate', order: -1 }}
                        footer={
                            searchConsoleMissing ? (
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    <Button
                                        variant="link"
                                        size="inline"
                                        nativeButton={false}
                                        render={<LinkPrimitive to={GOOGLE_SEARCH_CONSOLE_DOCS_URL} target="_blank" />}
                                    >
                                        Connect Google Search Console
                                    </Button>{' '}
                                    to see how often your site appears on Google for each keyword.
                                </Text>
                            ) : impressionsFailed ? (
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    Couldn't load the Search Console numbers.{' '}
                                    <Button variant="link" size="inline" onClick={loadImpressions}>
                                        Try again
                                    </Button>
                                </Text>
                            ) : undefined
                        }
                    />
                </div>
            )}
        </AiVisibilityCard>
    )
}
