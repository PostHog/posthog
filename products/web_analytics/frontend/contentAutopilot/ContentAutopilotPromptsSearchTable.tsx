import type { LemonTableColumn } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import type {
    AEOPromptSetSearchApi,
    BrandedSegmentEnumApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityTable } from './AiVisibilityTable'
import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { ContentAutopilotEngineMarks } from './ContentAutopilotEngineMarks'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import { ContentAutopilotSearchDetail } from './ContentAutopilotSearchDetail'

type SearchRow = AEOPromptSetSearchApi
type SearchColumn = LemonTableColumn<SearchRow, keyof SearchRow | undefined>

const citedShare = (row: SearchRow): number => (row.answers ? row.cited / row.answers : 0)

/** One row per web search the engines ran. A search opens the answers that ran it, and expanding a row shows the
 *  sites those answers cite, the searches that come with it and the prompts that ran it. */
export const ContentAutopilotPromptsSearchTable = ({
    rows,
    dateFrom,
    dateTo,
    branded,
    engine,
    topic,
    onOpenPrompt,
}: {
    rows: SearchRow[]
    /** The window of the report, so a row opens the same answers the report counted. */
    dateFrom: string
    dateTo: string
    branded: BrandedSegmentEnumApi
    /** The engine and topic filters of the report, so an expanded row counts the same answers. */
    engine: string | null
    topic: string | null
    onOpenPrompt: (promptId: string) => void
}): JSX.Element => {
    const columns: SearchColumn[] = [
        {
            title: 'Search',
            key: 'query',
            // The search takes the spare width and truncates, so the numbers never leave the card.
            className: 'w-full max-w-0',
            render: (_, row) => (
                <ContentAutopilotCitationsLink
                    lookup={{ kind: 'search', value: row.query, dateFrom, dateTo, branded }}
                    source="overview-searches"
                    className="font-semibold"
                    title={row.query}
                >
                    {row.query}
                </ContentAutopilotCitationsLink>
            ),
        },
        {
            title: 'Prompts',
            key: 'prompts',
            // A narrow card has no room for it next to the engine marks, and the expanded row lists the prompts.
            className: 'hidden @lg/searches:table-cell',
            align: 'right',
            tooltip: 'Different prompts whose answers ran this search.',
            sorter: (a, b) => a.prompts - b.prompts,
            render: (_, row) => <span className="tabular-nums">{row.prompts}</span>,
        },
        {
            title: 'Cited',
            key: 'cited',
            align: 'right',
            tooltip: 'How often the answers that ran this search linked to your site.',
            sorter: (a, b) => citedShare(a) - citedShare(b),
            render: (_, row) => (
                <ContentAutopilotRateBar
                    rate={row.answers ? citedShare(row) : null}
                    tooltip={`Out of ${pluralize(row.answers, 'answer')} that ran this search`}
                />
            ),
        },
        {
            title: 'Engines',
            key: 'engines',
            render: (_, row) => <ContentAutopilotEngineMarks engines={row.engines} />,
        },
    ]
    return (
        <div className="@container/searches">
            <AiVisibilityTable
                size="small"
                embedded
                dataSource={rows}
                rowKey="query"
                columns={columns}
                expandable={{
                    noIndent: true,
                    expandedRowRender: (row) => (
                        <ContentAutopilotSearchDetail
                            query={row.query}
                            dateFrom={dateFrom}
                            dateTo={dateTo}
                            branded={branded}
                            engine={engine}
                            topic={topic}
                            onOpenPrompt={onOpenPrompt}
                        />
                    ),
                }}
                emptyState="No web searches in this date range. Only some engines report the searches they run."
            />
        </div>
    )
}
