import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Query } from '~/queries/Query/Query'
import { QuerySchema } from '~/queries/schema/schema-general'
import { isSavedInsightNode } from '~/queries/utils'

import { getFilteredNotebookQuery, notebookFilteredBlockKey, NotebookFilters } from './notebookFilters'

export function NotebookFilteredQuery({
    shortId,
    nodeId,
    filters,
    unfiltered,
    query,
}: {
    shortId: string
    nodeId: string
    filters: NotebookFilters
    unfiltered: JSX.Element
    query: QuerySchema
}): JSX.Element {
    const savedId = isSavedInsightNode(query) ? query.shortId : null
    const { insight, insightLoading } = useValues(insightLogic({ dashboardItemId: savedId ?? 'new' }))
    if (savedId && !insight.query && insightLoading) {
        return <LemonSkeleton className="h-full w-full" />
    }
    const filtered = getFilteredNotebookQuery(savedId ? insight.query : query, filters)
    if (!filtered) {
        return (
            <div className="flex h-full flex-col">
                <LemonTag className="self-start">Notebook filters don’t apply to this query</LemonTag>
                {unfiltered}
            </div>
        )
    }
    const key = notebookFilteredBlockKey(shortId, nodeId, filters)
    return (
        <div className="flex h-full flex-col">
            <LemonTag className="self-start" type="highlight">
                Notebook filters applied
            </LemonTag>
            <Query key={key} uniqueKey={key} query={{ ...filtered, full: false, embedded: true }} embedded readOnly />
        </div>
    )
}
