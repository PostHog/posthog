import { LemonTable } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'

import type { AEOPageMoverApi, BrandedSegmentEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotCitationsLink } from './ContentAutopilotCitationsLink'
import { ContentAutopilotKpiDelta } from './ContentAutopilotKpiDelta'
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
    <LemonTable<AEOPageMoverApi>
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
                                    className="block w-full truncate"
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
                tooltip: `Share of the answers in this date range that cite the page, and how many did.`,
                render: (_, { citation_rate, answers_citing }) => (
                    <span className="tabular-nums whitespace-nowrap">
                        {percentage(citation_rate, 1)}{' '}
                        <span className="text-secondary">({answers_citing.toLocaleString()})</span>
                    </span>
                ),
            },
            {
                title: 'Before',
                key: 'previous_citation_rate',
                align: 'right',
                tooltip: `Share of the answers in the ${days} days before that cite the page, and how many did.`,
                render: (_, { previous_citation_rate, previous_answers_citing }) => (
                    <span className="tabular-nums whitespace-nowrap">
                        {percentage(previous_citation_rate, 1)}{' '}
                        <span className="text-secondary">({previous_answers_citing.toLocaleString()})</span>
                    </span>
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
