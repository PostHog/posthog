import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { ErrorTrackingSpikeEvent } from 'lib/components/Errors/types'

import type { batchSpikeEventsLogicType } from './batchSpikeEventsLogicType'

export const batchSpikeEventsLogic = kea<batchSpikeEventsLogicType>([
    path(['products', 'error_tracking', 'logics', 'batchSpikeEventsLogic']),

    actions({
        loadSpikeEventsForIssues: (issueIds: string[]) => ({ issueIds }),
    }),

    loaders({
        rawSpikeEvents: [
            [] as ErrorTrackingSpikeEvent[],
            {
                loadSpikeEventsForIssues: async ({ issueIds }, breakpoint) => {
                    if (issueIds.length === 0) {
                        return []
                    }
                    await breakpoint(100)
                    const response = await api.errorTracking.getBatchSpikeEvents(issueIds)
                    return response.results
                },
            },
        ],
    }),

    reducers({
        spikeEventsByIssueId: [
            {} as Record<string, ErrorTrackingSpikeEvent[]>,
            {
                loadSpikeEventsForIssuesSuccess: (_, { rawSpikeEvents }) => {
                    const grouped: Record<string, ErrorTrackingSpikeEvent[]> = {}
                    for (const event of rawSpikeEvents) {
                        const id = event.issue_id
                        if (!grouped[id]) {
                            grouped[id] = []
                        }
                        grouped[id].push(event)
                    }
                    return grouped
                },
            },
        ],
    }),
])
