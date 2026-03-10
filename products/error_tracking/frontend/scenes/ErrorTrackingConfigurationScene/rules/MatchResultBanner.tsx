import { combineUrl } from 'kea-router'

import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { NodeKind } from '~/queries/schema/schema-general'
import { ActivityTab, AnyPropertyFilter } from '~/types'

export function MatchResultBanner({
    matchResult,
    properties,
    suffix,
}: {
    matchResult: { exceptionCount: number; issueCount: number }
    properties: AnyPropertyFilter[]
    suffix: (issuesLink: JSX.Element) => JSX.Element
}): JSX.Element {
    if (matchResult.exceptionCount === 0) {
        return <span>No exceptions matched in the last 7 days</span>
    }

    const issuesUrl = urls.errorTracking({
        filterGroup: { type: 'AND', values: [{ type: 'AND', values: properties }] },
        dateRange: { date_from: '-7d', date_to: null },
    })

    const exceptionsUrl = combineUrl(
        urls.activity(ActivityTab.ExploreEvents),
        {},
        {
            q: {
                kind: NodeKind.DataTableNode,
                full: true,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: defaultDataTableColumns(NodeKind.EventsQuery),
                    orderBy: ['timestamp DESC'],
                    after: '-7d',
                    event: '$exception',
                    properties,
                },
                propertiesViaUrl: true,
                showPersistentColumnConfigurator: true,
            },
        }
    ).url

    const issuesLink = (
        <Link to={issuesUrl} target="_blank" externalLink targetBlankIcon={false}>
            {matchResult.issueCount.toLocaleString()} issue
            {matchResult.issueCount === 1 ? '' : 's'}
        </Link>
    )

    return (
        <span>
            <Link to={exceptionsUrl} target="_blank" externalLink targetBlankIcon={false}>
                {matchResult.exceptionCount.toLocaleString()} exception
                {matchResult.exceptionCount === 1 ? '' : 's'}
            </Link>{' '}
            {suffix(issuesLink)}
        </span>
    )
}
