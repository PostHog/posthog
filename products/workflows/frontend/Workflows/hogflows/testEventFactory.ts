import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils/dom'

import { CyclotronJobInvocationGlobals } from '~/types'

import { decodeSlackFilters } from './registry/triggers/slackTriggerFilters'

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

// Mirrors the flat property bag the Slack webhook handler emits for $slack_message_received
// (products/slack_app/backend/slack_workflow_events.py), so the test payload has the same shape
// a real trigger fire delivers. Slack-triggered runs carry no person.
export const createExampleSlackMessageEvent = (
    teamId?: number,
    workflowName?: string | null,
    channel: string = 'C0123456789'
): CyclotronJobInvocationGlobals => {
    const resolvedTeamId = teamId || 1
    const projectUrl = `${window.location.origin}/project/${resolvedTeamId}`
    const slackUser = 'U0123456789'
    const text = 'This is an example Slack message'
    const ts = `${dayjs().unix()}.000100`
    return {
        event: {
            uuid: uuid(),
            distinct_id: slackUser,
            timestamp: dayjs().toISOString(),
            elements_chain: '',
            url: '',
            event: '$slack_message_received',
            properties: {
                integration_id: 1,
                channel,
                channel_type: 'channel',
                slack_team_id: 'T0123456789',
                user: slackUser,
                bot_id: null,
                app_id: null,
                subtype: null,
                text,
                ts,
                thread_ts: null,
                is_thread_reply: false,
                is_ext_shared_channel: false,
                slack_event: { type: 'message', channel, channel_type: 'channel', user: slackUser, text, ts },
                this_is_an_example_event: true,
            },
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

// The example globals for a trigger type. Slack-message triggers get a message shaped like the
// real internal event, seeded with the trigger's own channel filter so it matches by default.
export const createExampleEventForTrigger = (
    triggerConfig: { type?: string; filters?: { properties?: Record<string, any>[] } } | undefined,
    teamId?: number,
    workflowName?: string | null
): CyclotronJobInvocationGlobals => {
    if (triggerConfig?.type === 'slack-message') {
        const channel = decodeSlackFilters(triggerConfig.filters?.properties).channel
        return createExampleSlackMessageEvent(teamId, workflowName, channel ?? undefined)
    }
    return createExampleEvent(teamId, workflowName)
}
