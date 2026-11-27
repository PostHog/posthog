import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconInfo } from '@posthog/icons'
import type { LemonTableColumn, LemonTableColumnGroup } from '@posthog/lemon-ui'
import { Button, Skeleton, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import type { Sorting } from 'lib/lemon-ui/LemonTable/sorting'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { AEOKeywordReportRowApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { GOOGLE_SEARCH_CONSOLE_DOCS_URL } from '../searchAndAi/searchAndAiQueries'
import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilityCard } from './AiVisibilityCard'
import { AiVisibilityTable } from './AiVisibilityTable'
import { contentAutopilotKeywordSearchLogic } from './contentAutopilotKeywordSearchLogic'
import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import type { KeywordSearchImpressions } from './keywordSearchImpressions'
import {
    MIN_RATED_ANSWERS,
    type ReportRateKey,
    type SampledRate,
    compareSampledRates,
    isRated,
    reportRate,
} from './keywordsReport'
import { windowRange } from './utils'

type ReportColumn = LemonTableColumn<AEOKeywordReportRowApi, keyof AEOKeywordReportRowApi | undefined>

/** A hint on hover for a value whose base is left out of the cell. */
const Hint = ({ title, children }: { title: string; children: React.ReactNode }): JSX.Element => (
    <Tooltip>
        <TooltipTrigger render={<span />}>{children}</TooltipTrigger>
        <TooltipContent className="max-w-80">{title}</TooltipContent>
    </Tooltip>
)

const DEFAULT_SORTING: Sorting = { columnKey: 'answer_mention_rate', order: -1 }

const Blank = (): JSX.Element => <span className="text-muted-foreground">-</span>

const UNIT_PLURALS = { answer: 'answers', search: 'searches' } as const

const TooFewAnswers = ({ sample, unit }: { sample: number; unit: keyof typeof UNIT_PLURALS }): JSX.Element => (
    <Hint
        title={`Fewer than ${pluralize(MIN_RATED_ANSWERS, unit, UNIT_PLURALS[unit])}, so a share would not mean much yet.`}
    >
        <span className="text-muted-foreground tabular-nums whitespace-nowrap">
            {pluralize(sample, unit, UNIT_PLURALS[unit])}
        </span>
    </Hint>
)

const RateOfSample = ({
    sampled,
    unit = 'answer',
}: {
    sampled: SampledRate
    unit?: keyof typeof UNIT_PLURALS
}): JSX.Element => {
    if (sampled.sample === 0) {
        return <Blank />
    }
    if (!isRated(sampled)) {
        return <TooFewAnswers sample={sampled.sample} unit={unit} />
    }
    return (
        <ContentAutopilotRateBar
            rate={sampled.rate}
            tooltip={`Out of ${pluralize(sampled.sample, unit, UNIT_PLURALS[unit])}`}
        />
    )
}

const RateOfAll = ({ sampled }: { sampled: SampledRate }): JSX.Element =>
    isRated(sampled) ? <ContentAutopilotRateBar rate={sampled.rate} /> : <Blank />

const Decimal = ({ value }: { value: number | null }): JSX.Element =>
    value === null ? <Blank /> : <span className="tabular-nums">{value.toFixed(1)}</span>

const KEYWORD_COLUMN: ReportColumn = {
    title: 'Keyword',
    key: 'keyword',
    render: (_, row) => <span className="font-semibold">{row.keyword}</span>,
    sorter: (a, b) => a.keyword.localeCompare(b.keyword),
}

const rateColumn = (
    key: ReportRateKey,
    totalAnswers: number,
    order: 1 | -1,
    column: Pick<ReportColumn, 'title' | 'key' | 'tooltip' | 'render'>
): ReportColumn => {
    const compare = compareSampledRates(order)
    return {
        ...column,
        align: 'right',
        sorter: (a, b) => compare(reportRate(a, key, totalAnswers), reportRate(b, key, totalAnswers)),
    }
}

const aiColumns = (totalAnswers: number, order: 1 | -1): ReportColumn[] => [
    rateColumn('visibility', totalAnswers, order, {
        title: 'Visibility',
        key: 'answer_mention_rate',
        tooltip:
            'Of the answers whose text contains this keyword, the share that name your brand or link to your site.',
        render: (_, row) => <RateOfSample sampled={reportRate(row, 'visibility', totalAnswers)} />,
    }),
    rateColumn('searched', totalAnswers, order, {
        title: 'Searched',
        key: 'searched_rate',
        tooltip: `Of all ${pluralize(totalAnswers, 'answer')} in this window, the share where the engine searched the web for this keyword.`,
        render: (_, row) => <RateOfAll sampled={reportRate(row, 'searched', totalAnswers)} />,
    }),
    rateColumn('searched_cited', totalAnswers, order, {
        title: 'Cited when searched',
        key: 'searched_cited_rate',
        tooltip: 'Of the answers whose web searches contain this keyword, the share that link to your site.',
        render: (_, row) => <RateOfSample sampled={reportRate(row, 'searched_cited', totalAnswers)} unit="search" />,
    }),
]

const Detail = ({ label, children }: { label: string; children: React.ReactNode }): JSX.Element => (
    <div className="flex flex-col gap-0.5 min-w-0">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="text-sm">{children}</span>
    </div>
)

const KeywordDetails = ({ row, totalAnswers }: { row: AEOKeywordReportRowApi; totalAnswers: number }): JSX.Element => (
    <div
        className="grid grid-cols-2 @xl/ai-visibility-table:grid-cols-3 @5xl/ai-visibility-table:grid-cols-6 gap-x-6 gap-y-3 px-2 py-1"
        data-attr="content-autopilot-keywords-report-details"
    >
        <Detail label="In prompts">
            {row.prompts ? (
                <Hint title="Prompts whose text contains this keyword and that ran in this window.">
                    <span className="tabular-nums">{pluralize(row.prompts, 'prompt')}</span>
                </Hint>
            ) : (
                <Blank />
            )}
        </Detail>
        <Detail label="Prompt visibility">
            <Hint title="Of the answers to prompts that contain this keyword, the share that name your brand.">
                <span>
                    <RateOfSample sampled={reportRate(row, 'prompt_mention', totalAnswers)} />
                </span>
            </Hint>
        </Detail>
        <Detail label="Prompt citations">
            <Hint title="Of the answers to prompts that contain this keyword, the share that link to your site.">
                <span>
                    <RateOfSample sampled={reportRate(row, 'prompt_cited', totalAnswers)} />
                </span>
            </Hint>
        </Detail>
        <Detail label="Uses per answer">
            <Hint title="How many times an answer that contains this keyword repeats it, on average.">
                <span>
                    <Decimal value={row.uses_per_answer} />
                </span>
            </Hint>
        </Detail>
        <Detail label="Citation position">
            <Hint title="Where your site ranks among the cited sources, on average, in answers that contain this keyword and cite you. 1 is first.">
                <span>
                    <Decimal value={row.avg_citation_position} />
                </span>
            </Hint>
        </Detail>
        <Detail label="First mention">
            <Hint title="How far into the answer your brand is first named, as a share of its length. 0% is the first sentence. Median over the answers that contain this keyword and name your brand.">
                <span>
                    {row.median_first_mention_depth === null ? (
                        <Blank />
                    ) : (
                        <span className="tabular-nums">
                            {percentage(row.median_first_mention_depth, 0)} into the answer
                        </span>
                    )}
                </span>
            </Hint>
        </Detail>
    </div>
)

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
    // The sort order is kept here so the rate comparators can hold rows without enough answers at the bottom
    // in both directions.
    const [sorting, setSorting] = useState<Sorting | null>(DEFAULT_SORTING)
    const totalAnswers = report?.answers ?? 0
    const columns: LemonTableColumnGroup<AEOKeywordReportRowApi>[] = [
        { children: [KEYWORD_COLUMN] },
        {
            title: (
                <GroupTitle
                    title="AI answers"
                    description={`An answer or search counts for a keyword when its text contains the keyword. A share needs at least ${MIN_RATED_ANSWERS} answers; below that the count shows instead. Expand a row for prompts, uses per answer, citation position and first mention.`}
                />
            ),
            children: aiColumns(totalAnswers, sorting?.order ?? -1),
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
        <AiVisibilityCard title="How your keywords perform">
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
                        sorting={sorting}
                        onSort={setSorting}
                        expandable={{
                            expandedRowRender: (row) => <KeywordDetails row={row} totalAnswers={totalAnswers} />,
                            rowExpandable: () => true,
                            noIndent: true,
                        }}
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
