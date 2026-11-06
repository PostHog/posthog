import { Survey, UserBasicType } from '~/types'

import type { ActivityLogEntryApi } from 'products/surveys/frontend/generated/api.schemas'

export type SurveyChannel = 'app' | 'mcp' | 'api' | 'scout'

export interface SurveyEdit {
    by: UserBasicType | null
    at: string
    channel: SurveyChannel
}

export interface SurveyProvenance {
    createdBy: UserBasicType | null
    createdAt: string
    /** Null when the activity log has no `created` entry to read it from. */
    channel: SurveyChannel | null
    agentIntent: string | null
    lastEdit: SurveyEdit | null
}

export const SURVEY_CHANNEL_LABELS: Record<SurveyChannel, string> = {
    app: 'the PostHog app',
    mcp: 'MCP',
    api: 'the API',
    scout: 'a scout',
}

// Keys are the stored `client` tag: an exact self-reported header value, or a server-derived prefix ending in ':'.
// A Map, not an object, because `client` is caller-supplied and `constructor` or `__proto__` must stay unknown.
const CHANNEL_BY_CLIENT = new Map<string, SurveyChannel>([
    ['mcp', 'mcp'],
    ['scout:', 'scout'],
])

function getChannel(client: string | null): SurveyChannel {
    if (client === null) {
        return 'app'
    }
    const tag = client.toLowerCase()
    return CHANNEL_BY_CLIENT.get(tag) ?? CHANNEL_BY_CLIENT.get(tag.slice(0, tag.indexOf(':') + 1)) ?? 'api'
}

function getIntent(entry: ActivityLogEntryApi): string | null {
    const payload = entry.detail?.trigger?.payload
    const intent = payload && typeof payload === 'object' && 'intent' in payload ? payload.intent : null
    return typeof intent === 'string' && intent.trim() ? intent : null
}

/** `entries` is the survey's activity, newest first, or null when it couldn't be loaded. */
export function getSurveyProvenance(
    survey: Pick<Survey, 'created_by' | 'created_at'>,
    entries: ActivityLogEntryApi[] | null
): SurveyProvenance {
    const created = entries?.find((entry) => entry.activity === 'created')
    const lastUpdate = entries?.find((entry) => entry.activity === 'updated')
    return {
        createdBy: survey.created_by,
        createdAt: survey.created_at,
        channel: created ? getChannel(created.client) : null,
        agentIntent:
            (created ? getIntent(created) : null) ?? entries?.map(getIntent).find((intent) => intent !== null) ?? null,
        lastEdit: lastUpdate
            ? {
                  // The serializer types `user` as a free-form object, but it carries UserBasicSerializer's fields.
                  by: lastUpdate.user as UserBasicType | null,
                  at: lastUpdate.created_at,
                  channel: getChannel(lastUpdate.client),
              }
            : null,
    }
}
