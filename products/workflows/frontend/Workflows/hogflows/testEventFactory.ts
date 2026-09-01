import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils/dom'

import { CyclotronJobInvocationGlobals } from '~/types'

// A pure, kea-free factory for a synthetic test event/person - kept out of hogFlowEditorTestLogic
// so callers that only need example data don't pull in the workflow editor's kea logic graph.
export const createExampleEvent = (
    teamId?: number,
    workflowName?: string | null,
    eventName: string = '$pageview',
    email: string = 'example@posthog.com'
): CyclotronJobInvocationGlobals => {
    const resolvedTeamId = teamId || 1
    const projectUrl = `${window.location.origin}/project/${resolvedTeamId}`
    const eventUuid = uuid()
    const eventTimestamp = dayjs().toISOString()
    return {
        event: {
            uuid: eventUuid,
            distinct_id: uuid(),
            timestamp: eventTimestamp,
            elements_chain: '',
            url: `${projectUrl}/events/${encodeURIComponent(eventUuid)}/${encodeURIComponent(eventTimestamp)}`,
            event: eventName,
            properties: {
                $current_url: window.location.href.split('#')[0],
                $browser: 'Chrome',
                this_is_an_example_event: true,
            },
        },
        person: {
            id: uuid(),
            properties: {
                email,
            },
            name: 'Example person',
            url: `${window.location.origin}/person/${uuid()}`,
        },
        groups: {},
        project: {
            id: resolvedTeamId,
            name: 'Default project',
            url: projectUrl,
        },
        source: {
            name: workflowName ?? 'Unnamed',
            url: window.location.href.split('#')[0],
        },
    }
}
