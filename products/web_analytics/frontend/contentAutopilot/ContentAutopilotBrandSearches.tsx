import type { AEOBrandSearchApi, BrandedSegmentEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityTable } from './AiVisibilityTable'
import { REPORT_TABLE_PAGE_SIZE } from './aiVisibilityTablePaging'
import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { ContentAutopilotEngineMarks } from './ContentAutopilotEngineMarks'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import { ContentAutopilotSearchDetail } from './ContentAutopilotSearchDetail'

/** The web searches the answers naming a brand ran. A search opens its answers, and expanding it shows the search
 *  detail over the same filters. */
export const ContentAutopilotBrandSearches = ({
    searches,
    dateFrom,
    dateTo,
    branded,
    engine,
    topic,
    onOpenPrompt,
}: {
    searches: AEOBrandSearchApi[]
    dateFrom: string
    dateTo: string
    branded: BrandedSegmentEnumApi
    engine: string | null
    topic: string | null
    onOpenPrompt: (promptId: string) => void
}): JSX.Element => (
    <AiVisibilityTable<AEOBrandSearchApi>
        size="small"
        data-attr="content-autopilot-brand-searches"
        pagination={{ pageSize: REPORT_TABLE_PAGE_SIZE }}
        emptyState="No web searches in this date range."
        dataSource={searches}
        rowKey="query"
        expandable={{
            noIndent: true,
            expandedRowRender: (search) => (
                <ContentAutopilotSearchDetail
                    query={search.query}
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    branded={branded}
                    engine={engine}
                    topic={topic}
                    onOpenPrompt={onOpenPrompt}
                />
            ),
        }}
        columns={[
            {
                title: 'Search',
                key: 'query',
                className: 'w-full max-w-0',
                render: (_, search) => (
                    <ContentAutopilotCitationsLink
                        lookup={{ kind: 'search', value: search.query, dateFrom, dateTo, branded, engine, topic }}
                        source="brand-searches"
                        title={search.query}
                    >
                        {search.query}
                    </ContentAutopilotCitationsLink>
                ),
            },
            {
                title: 'Engines',
                key: 'engines',
                className: 'hidden @md/ai-visibility-table:table-cell',
                render: (_, search) => <ContentAutopilotEngineMarks engines={search.engines} />,
            },
            {
                title: 'Share of answers',
                key: 'share_of_answers',
                align: 'right',
                tooltip: 'Share of the answers naming the brand that ran this search.',
                sorter: (a, b) => a.share_of_answers - b.share_of_answers,
                render: (_, search) => <ContentAutopilotRateBar rate={search.share_of_answers} />,
            },
        ]}
    />
)
