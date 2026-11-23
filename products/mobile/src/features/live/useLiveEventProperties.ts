import { type UseQueryResult, useQuery } from '@tanstack/react-query'

import { fetchLiveEventProperties } from '@/api/live'
import { type ProjectScope, retryUnlessMissing, scopeKey } from '@/api/reports'
import { demoLiveEventProperties } from '@/demo/live'
import type { LiveEventRow } from '@/model/live'

export function useLiveEventProperties(
    event: LiveEventRow,
    scope: ProjectScope | null,
    active: boolean
): UseQueryResult<Record<string, unknown>, unknown> {
    return useQuery({
        queryKey: ['live-event-properties', ...scopeKey(scope), event.id],
        queryFn: ({ signal }) =>
            scope ? fetchLiveEventProperties(event.id, scope, signal) : Promise.resolve(demoLiveEventProperties(event)),
        enabled: active,
        staleTime: Infinity,
        retry: retryUnlessMissing,
    })
}
