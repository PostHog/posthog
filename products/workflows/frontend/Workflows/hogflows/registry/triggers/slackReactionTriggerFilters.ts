import { PropertyFilterType, PropertyOperator } from '~/types'

import { channelId } from './slackTriggerFilters'

/** Who is allowed to start a run by reacting. Each mode compiles to exactly one property filter. */
export type SlackReactorMode = 'anyone' | 'specific_people'

export const SLACK_REACTOR_MODE_OPTIONS: { value: SlackReactorMode; label: string; description: string }[] = [
    {
        value: 'anyone',
        label: 'Anyone',
        description: 'Everyone in the channel can start a run.',
    },
    {
        value: 'specific_people',
        label: 'Specific people',
        description: 'Only the Slack users you list can start a run.',
    },
]

/**
 * Property keys the native controls own. Anything else a person adds survives untouched in the
 * advanced list, so the two editors never fight over the same entry.
 */
const OWNED_KEYS = new Set(['channel', 'reaction', 'user'])

export interface SlackReactionTriggerFilters {
    channel: string | null
    reactions: string[]
    reactorMode: SlackReactorMode
    reactorIds: string[]
    additional: Record<string, any>[]
}

/**
 * The emoji name as the event carries it: no colons, no skin tone.
 *
 * People type `:mag:` because that is what they see in Slack, and Slack sends `mag`. A filter
 * storing the typed form would never match. The emit strips skin tone from the event side, so
 * stripping it here keeps the two halves reading the same value.
 */
export function reactionName(value: string): string {
    return value
        .trim()
        .replace(/^:+|:+$/g, '')
        .split('::')[0]
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

export function decodeSlackReactionFilters(properties: Record<string, any>[] | undefined): SlackReactionTriggerFilters {
    const list = Array.isArray(properties) ? properties : []
    const channelEntry = find(list, 'channel')
    const reactionEntry = find(list, 'reaction')
    const user = find(list, 'user')

    return {
        channel: values(channelEntry).length ? channelId(values(channelEntry)[0]) : null,
        reactions: values(reactionEntry),
        // Keyed on the entry existing, not on it having values: the mode is chosen before any id is
        // typed, and reading the values would snap the control back to "anyone" while you fill it in.
        reactorMode: user ? 'specific_people' : 'anyone',
        reactorIds: values(user),
        additional: list.filter((property) => !OWNED_KEYS.has(property?.key)),
    }
}

export function encodeSlackReactionFilters(filters: SlackReactionTriggerFilters): Record<string, any>[] {
    const properties: Record<string, any>[] = []

    if (filters.channel) {
        properties.push(exact('channel', [channelId(filters.channel)]))
    }

    const reactions = filters.reactions.map(reactionName).filter(Boolean)
    if (reactions.length) {
        properties.push(exact('reaction', reactions))
    }

    if (filters.reactorMode === 'specific_people') {
        properties.push(exact('user', filters.reactorIds))
    }

    return [...properties, ...filters.additional]
}
