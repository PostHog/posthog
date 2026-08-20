import { PropertyFilterType, PropertyOperator } from '~/types'

/** Who is allowed to start a run. Each mode compiles to exactly one property filter. */
export type SlackPosterMode = 'anyone' | 'people' | 'specific_people' | 'apps' | 'specific_apps'

export const SLACK_POSTER_MODE_OPTIONS: { value: SlackPosterMode; label: string; description: string }[] = [
    {
        value: 'people',
        label: 'People only',
        description: 'Skips anything posted by an app or bot.',
    },
    {
        value: 'specific_people',
        label: 'Specific people',
        description: 'Only messages from the Slack users you list.',
    },
    {
        value: 'apps',
        label: 'Apps and bots only',
        description: 'For alerts posted by another tool rather than typed by a person.',
    },
    {
        value: 'specific_apps',
        label: 'Specific apps',
        description: 'Only messages from the Slack apps you list.',
    },
    {
        value: 'anyone',
        label: 'Anyone',
        description: 'Every message in the channel, from people and from other apps.',
    },
]

/**
 * Property keys the native controls own. Anything else a person adds survives untouched in the
 * advanced list, so the two editors never fight over the same entry.
 */
const OWNED_KEYS = new Set(['channel', 'user', 'bot_id', 'app_id', 'thread_ts'])

export interface SlackTriggerFilters {
    channel: string | null
    posterMode: SlackPosterMode
    posterIds: string[]
    topLevelOnly: boolean
    additional: Record<string, any>[]
}

/** The picker round-trips a channel as `C123|#name`, but the event carries the bare id. */
export function channelId(value: string): string {
    return value.split('|')[0]
}

function find(properties: Record<string, any>[], key: string): Record<string, any> | undefined {
    return properties.find((property) => property?.key === key)
}

function values(entry: Record<string, any> | undefined): string[] {
    if (!entry) {
        return []
    }
    const value = Array.isArray(entry.value) ? entry.value : [entry.value]
    return value.filter((item: unknown): item is string => typeof item === 'string' && item !== '')
}

function exact(key: string, value: string[]): Record<string, any> {
    return { key, value, operator: PropertyOperator.Exact, type: PropertyFilterType.Event }
}

function presence(key: string, operator: PropertyOperator): Record<string, any> {
    return { key, value: operator, operator, type: PropertyFilterType.Event }
}

export function decodeSlackFilters(properties: Record<string, any>[] | undefined): SlackTriggerFilters {
    const list = Array.isArray(properties) ? properties : []
    const channelEntry = find(list, 'channel')
    const user = find(list, 'user')
    const appId = find(list, 'app_id')
    const botId = find(list, 'bot_id')
    const threadTs = find(list, 'thread_ts')

    let posterMode: SlackPosterMode = 'anyone'
    let posterIds: string[] = []
    // Keyed on the entry existing, not on it having values: the mode is chosen before any id is
    // typed, and reading the values would snap the control back to "anyone" while you fill it in.
    if (user) {
        posterMode = 'specific_people'
        posterIds = values(user)
    } else if (appId) {
        posterMode = 'specific_apps'
        posterIds = values(appId)
    } else if (botId?.operator === PropertyOperator.IsSet) {
        posterMode = 'apps'
    } else if (botId?.operator === PropertyOperator.IsNotSet) {
        posterMode = 'people'
    }

    return {
        channel: values(channelEntry).length ? channelId(values(channelEntry)[0]) : null,
        posterMode,
        posterIds,
        topLevelOnly: threadTs?.operator === PropertyOperator.IsNotSet,
        additional: list.filter((property) => !OWNED_KEYS.has(property?.key)),
    }
}

export function encodeSlackFilters(filters: SlackTriggerFilters): Record<string, any>[] {
    const properties: Record<string, any>[] = []

    if (filters.channel) {
        properties.push(exact('channel', [channelId(filters.channel)]))
    }

    switch (filters.posterMode) {
        case 'people':
            properties.push(presence('bot_id', PropertyOperator.IsNotSet))
            break
        case 'apps':
            properties.push(presence('bot_id', PropertyOperator.IsSet))
            break
        case 'specific_people':
            properties.push(exact('user', filters.posterIds))
            break
        case 'specific_apps':
            properties.push(exact('app_id', filters.posterIds))
            break
        case 'anyone':
            break
    }

    if (filters.topLevelOnly) {
        // A top-level post carries no thread_ts, so absence is what separates it from a reply.
        // Avoids comparing against the boolean is_thread_reply, where a string/bool mismatch
        // would silently never match.
        properties.push(presence('thread_ts', PropertyOperator.IsNotSet))
    }

    return [...properties, ...filters.additional]
}
