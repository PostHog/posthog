import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Query } from '~/queries/Query/Query'
import { QuerySchema } from '~/queries/schema/schema-general'
import { isSavedInsightNode } from '~/queries/utils'

import { getNotebookCohortQuery } from './notebookCohortPreview'

export function NotebookCohortQueryPreview({
    shortId,
    nodeId,
    cohortId,
    query,
}: {
    shortId: string
    nodeId: string
    cohortId: number
    query: QuerySchema
}): JSX.Element {
    const savedId = isSavedInsightNode(query) ? query.shortId : null
    const { insight, insightLoading } = useValues(insightLogic({ dashboardItemId: savedId ?? 'new' }))
    if (savedId && !insight.query && insightLoading) {
        return <LemonSkeleton className="h-full w-full" />
    }
    const filtered = getNotebookCohortQuery(savedId ? insight.query : query, cohortId)
    if (!filtered) {
        return <div className="p-3 text-secondary">Clear the cohort filter to view this query.</div>
    }
    const key = `notebook-cohort-${shortId}-${nodeId}-${cohortId}`
    return (
        <div className="flex h-full flex-col">
            <LemonTag className="self-start" type="highlight">
                Cohort preview
            </LemonTag>
            <Query key={key} uniqueKey={key} query={{ ...filtered, full: false, embedded: true }} embedded readOnly />
        </div>
    )
}
