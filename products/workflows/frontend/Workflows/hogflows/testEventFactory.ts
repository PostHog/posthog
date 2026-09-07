import { dayjs } from 'lib/dayjs'
import { uuid } from 'lib/utils/dom'

import { CyclotronJobInvocationGlobals } from '~/types'

import {
    SlackTriggerFilters,
    decodeSlackFilters,
    isSlackMessageTriggerConfig,
} from './registry/triggers/slackTriggerFilters'

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
//
// `filters` seeds the fields the trigger's own channel and poster-mode filters read, so the
// generated sample matches those native filters by construction. It cannot seed an advanced
// filter added through `additional` (e.g. on `text` or `subtype`) - those still need manual edits.
export const createExampleSlackMessageEvent = (
    teamId?: number,
    workflowName?: string | null,
    filters: Partial<SlackTriggerFilters> = {}
): CyclotronJobInvocationGlobals => {
    const resolvedTeamId = teamId || 1
    const projectUrl = `${window.location.origin}/project/${resolvedTeamId}`
    const channel = filters.channel ?? 'C0123456789'
    const posterId = filters.posterIds?.[0]
    // Defaults satisfy 'anyone' and 'people' (no bot_id); each other native poster mode
    // overrides only the field its own filter reads.
    let user: string | null = 'U0123456789'
    let botId: string | null = null
    let appId: string | null = null
    switch (filters.posterMode) {
        case 'apps':
            botId = 'B0123456789'
            appId = 'A0123456789'
            user = null
            break
        case 'specific_apps':
            appId = posterId ?? 'A0123456789'
            botId = 'B0123456789'
            user = null
            break
        case 'specific_people':
            user = posterId ?? user
            break
    }
    const text = 'This is an example Slack message'
    const ts = `${dayjs().unix()}.000100`
    return {
        event: {
            uuid: uuid(),
            distinct_id: user ?? botId ?? channel,
            timestamp: dayjs().toISOString(),
            elements_chain: '',
            url: '',
            event: '$slack_message_received',
            properties: {
                integration_id: 1,
                channel,
                channel_type: 'channel',
                slack_team_id: 'T0123456789',
                user,
                bot_id: botId,
                app_id: appId,
                subtype: null,
                text,
                ts,
                thread_ts: null,
                is_thread_reply: false,
                is_ext_shared_channel: false,
                slack_event: { type: 'message', channel, channel_type: 'channel', user, text, ts },
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

// The example globals for a trigger type. A Slack-connected internal-event trigger gets a
// message shaped like the real internal event, seeded with the trigger's own channel and poster
// filters so it matches those by default.
export const createExampleEventForTrigger = (
    triggerConfig: unknown,
    teamId?: number,
    workflowName?: string | null
): CyclotronJobInvocationGlobals => {
    if (isSlackMessageTriggerConfig(triggerConfig)) {
        const decoded = decodeSlackFilters(triggerConfig.filters.properties)
        return createExampleSlackMessageEvent(teamId, workflowName, decoded)
    }
    return createExampleEvent(teamId, workflowName)
}
