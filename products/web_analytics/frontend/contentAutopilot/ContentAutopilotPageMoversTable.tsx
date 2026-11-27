import { pluralize } from 'lib/utils/strings'

import type { AEOPageMoverApi, BrandedSegmentEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { AiVisibilityTable } from './AiVisibilityTable'
import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { ContentAutopilotKpiDelta } from './ContentAutopilotKpiDelta'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import { moverDelta } from './movers'

/** The pages on your site that moved, gains first. A page opens the answers that cite it now. */
export const ContentAutopilotPageMoversTable = ({
    rows,
    days,
    dateFrom,
    dateTo,
    branded,
}: {
    rows: AEOPageMoverApi[]
    days: number
    dateFrom: string
    dateTo: string
    branded: BrandedSegmentEnumApi
}): JSX.Element => (
    <AiVisibilityTable<AEOPageMoverApi>
        size="small"
        embedded
        dataSource={rows}
        rowKey="url"
        columns={[
            {
                title: 'Page',
                key: 'url',
                // The cell takes the width the numbers leave, and the text truncates to it.
                className: 'w-full max-w-0',
                render: (_, { url, answers_citing }) => {
                    const label = url.replace(/^https?:\/\//, '')
                    // A page that no answer cites now has no answers to open.
                    return (
                        <span className="block truncate font-semibold" title={url}>
                            {answers_citing > 0 ? (
                                <ContentAutopilotCitationsLink
                                    lookup={{ kind: 'url', value: url, dateFrom, dateTo, branded }}
                                    source="overview-movers"
                                    // A button sizes to its text, so it needs the cell's width to truncate.
                                    className="w-full"
                                >
                                    {label}
                                </ContentAutopilotCitationsLink>
                            ) : (
                                label
                            )}
                        </span>
                    )
                },
            },
            {
                title: 'Now',
                key: 'citation_rate',
                align: 'right',
                tooltip: 'Share of all answers in this date range that link to this page.',
                render: (_, { citation_rate, answers_citing }) => (
                    <ContentAutopilotRateBar
                        rate={citation_rate}
                        tooltip={`Cited in ${pluralize(answers_citing, 'answer')}`}
                    />
                ),
            },
            {
                title: 'Before',
                key: 'previous_citation_rate',
                align: 'right',
                tooltip: `Share of all answers in the ${days} days before that link to this page.`,
                render: (_, { previous_citation_rate, previous_answers_citing }) => (
                    <ContentAutopilotRateBar
                        rate={previous_citation_rate}
                        tooltip={`Cited in ${pluralize(previous_answers_citing, 'answer')}`}
                    />
                ),
            },
            {
                title: 'Change',
                key: 'change',
                align: 'right',
                render: (_, { change }) => <ContentAutopilotKpiDelta delta={moverDelta(change, days)} />,
            },
        ]}
    />
)
