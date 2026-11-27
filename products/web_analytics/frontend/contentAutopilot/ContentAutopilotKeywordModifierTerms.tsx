import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type {
    AEOKeywordModifierApi,
    BrandedSegmentEnumApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityTable } from './AiVisibilityTable'
import { AiVisibilityTag } from './AiVisibilityTag'
import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import { isCitationGap } from './keywordsReport'
import { engineLabel } from './utils'

/** The words of one modifier group, with gaps against the baseline cited rate highlighted. */
export const ContentAutopilotKeywordModifierTerms = ({
    modifiers,
    baselineCitedRate,
    dateFrom,
    dateTo,
    branded,
}: {
    modifiers: AEOKeywordModifierApi[]
    /** The window and branded split of the report, so a search opens the same answers the report counted. */
    dateFrom: string
    dateTo: string
    branded: BrandedSegmentEnumApi
    baselineCitedRate: number | null
}): JSX.Element => (
    <AiVisibilityTable<AEOKeywordModifierApi>
        size="small"
        embedded
        dataSource={modifiers}
        rowKey="term"
        rowStatus={(modifier) => (isCitationGap(modifier, baselineCitedRate) ? 'highlighted' : null)}
        columns={[
            {
                title: 'Word',
                key: 'term',
                render: (_, modifier) => <span className="font-semibold">{modifier.term}</span>,
            },
            {
                title: 'Answers',
                key: 'share',
                align: 'right',
                tooltip: 'Share of answers whose searches used this word.',
                render: (_, modifier) => (
                    <ContentAutopilotRateBar
                        rate={modifier.share}
                        tooltip={`${pluralize(modifier.answers, 'answer')}`}
                    />
                ),
            },
            {
                title: 'Cited',
                key: 'cited_rate',
                align: 'right',
                tooltip: 'How often those answers cite your site, against all answers.',
                render: (_, modifier) => (
                    <span className="flex items-center justify-end gap-2 tabular-nums">
                        {isCitationGap(modifier, baselineCitedRate) ? (
                            <AiVisibilityTag type="danger">Gap</AiVisibilityTag>
                        ) : null}
                        <ContentAutopilotRateBar
                            rate={modifier.cited_rate}
                            tooltip={
                                baselineCitedRate !== null
                                    ? `Against ${percentage(baselineCitedRate, 0)} across all answers`
                                    : undefined
                            }
                        />
                    </span>
                ),
            },
            {
                title: 'Engines',
                key: 'engines',
                render: (_, modifier) => (
                    <span className="text-muted-foreground">
                        {modifier.engines.map((engine) => `${engineLabel(engine.engine)} ${engine.answers}`).join(', ')}
                    </span>
                ),
            },
            {
                title: 'Example searches',
                key: 'example_searches',
                render: (_, modifier) => (
                    <ul className="m-0 flex flex-col gap-0.5 max-w-120">
                        {modifier.example_searches.map((search) => (
                            <li key={search} className="flex min-w-0 text-xs">
                                <ContentAutopilotCitationsLink
                                    lookup={{ kind: 'search', value: search, dateFrom, dateTo, branded }}
                                    source="keyword-modifier-searches"
                                    title={search}
                                >
                                    {search}
                                </ContentAutopilotCitationsLink>
                            </li>
                        ))}
                    </ul>
                ),
            },
        ]}
    />
)
