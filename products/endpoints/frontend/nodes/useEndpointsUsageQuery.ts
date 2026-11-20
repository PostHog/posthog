import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    EndpointsUsageOverviewQuery,
    EndpointsUsageTableQuery,
    EndpointsUsageTrendsQuery,
} from '~/queries/schema/schema-general'

type EndpointsUsageQuery = EndpointsUsageOverviewQuery | EndpointsUsageTableQuery | EndpointsUsageTrendsQuery

interface EndpointsUsageQueryState<R> {
    response: R | undefined
    responseLoading: boolean
    responseError: string | null
    retry: () => void
}

let uniqueKey = 0

/** Runs one usage query without the `Query` wrapper, so the Quill cards can lay out loading, error and data themselves. */
export function useEndpointsUsageQuery<R extends AnyResponseType>(
    query: EndpointsUsageQuery
): EndpointsUsageQueryState<R> {
    const [key] = useState(() => `EndpointsUsageQuery.${uniqueKey++}`)
    const logic = dataNodeLogic({ query, key, dataNodeCollectionId: key })
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)

    return {
        response: (response ?? undefined) as R | undefined,
        responseLoading,
        responseError,
        retry: () => loadData(),
    }
}
