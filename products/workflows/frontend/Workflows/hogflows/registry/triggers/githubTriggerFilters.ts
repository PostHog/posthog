import { PropertyFilterType, PropertyOperator } from '~/types'

/** pinned: analytics event name emitted by the GitHub trigger */
const GITHUB_EVENT_RECEIVED_EVENT = '$github_event_received'

/** The stored trigger config a GitHub workflow uses. */
export type InternalEventGithubTriggerConfig = {
    type: 'internal-event'
    filters: {
        source: 'internal-events'
        events: { id: string; type: 'events' }[]
        properties?: any[]
    }
}

// Callers pass whatever trigger a workflow carries, including malformed shapes, so every level is
// checked before it is read.
export function isGithubEventTriggerConfig(config: unknown): config is InternalEventGithubTriggerConfig {
    if (!config || typeof config !== 'object') {
        return false
    }
    const { type, filters } = config as { type?: unknown; filters?: unknown }
    if (type !== 'internal-event' || !filters || typeof filters !== 'object') {
        return false
    }
    const { source, events } = filters as { source?: unknown; events?: unknown }
    return (
        source === 'internal-events' &&
        Array.isArray(events) &&
        events.some(
            (event) =>
                event && typeof event === 'object' && (event as { id?: unknown }).id === GITHUB_EVENT_RECEIVED_EVENT
        )
    )
}

/** Who is allowed to start a run. Each mode compiles to exactly one property filter. */
export type GithubActorMode = 'write_access' | 'anyone' | 'people' | 'specific_people'

export const GITHUB_ACTOR_MODE_OPTIONS: { value: GithubActorMode; label: string; description: string }[] = [
    {
        value: 'write_access',
        label: 'People with write access',
        description: 'Owners, members and collaborators, plus any push. Skips drive-by issues and comments.',
    },
    {
        value: 'specific_people',
        label: 'Specific people',
        description: 'Only activity from the GitHub usernames you list.',
    },
    {
        value: 'people',
        label: 'Anyone except bots',
        description: 'Includes people with no access to the repository, so treat the content as untrusted.',
    },
    {
        value: 'anyone',
        label: 'Anyone',
        description: 'Every delivery, including bots and people with no access to the repository.',
    },
]

// Each option matches a whole GitHub webhook event, not a single action: "issues" also
// covers labeled/assigned/etc, and "push" covers a branch or tag delete with no commits.
// Labels stay broad so they don't promise a narrower set than the filter matches; the
// "action" advanced filter narrows further.
export const GITHUB_EVENT_TYPE_OPTIONS: { value: string; label: string }[] = [
    { value: 'issues', label: 'Issue activity' },
    { value: 'issue_comment', label: 'Comment on an issue or pull request' },
    { value: 'pull_request', label: 'Pull request activity' },
    { value: 'pull_request_review', label: 'Pull request reviewed' },
    { value: 'push', label: 'Push activity' },
]

/**
 * Property keys the native controls own. Anything else a person adds survives untouched in the
 * advanced list, so the two editors never fight over the same entry.
 */
const OWNED_KEYS = new Set(['repository', 'event_type', 'actor_access', 'sender', 'bot_sender'])

export interface GithubTriggerFilters {
    repository: string | null
    eventTypes: string[]
    actorMode: GithubActorMode
    actorLogins: string[]
    additional: Record<string, any>[]
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

export function decodeGithubFilters(properties: Record<string, any>[] | undefined): GithubTriggerFilters {
    const list = Array.isArray(properties) ? properties : []
    const repository = find(list, 'repository')
    const eventTypes = find(list, 'event_type')
    const sender = find(list, 'sender')
    const actorAccess = find(list, 'actor_access')
    const botSender = find(list, 'bot_sender')

    let actorMode: GithubActorMode = 'anyone'
    let actorLogins: string[] = []
    // Keyed on the entry existing, not on it having values: the mode is chosen before any login is
    // typed, and reading the values would snap the control back while you fill it in.
    if (sender) {
        actorMode = 'specific_people'
        actorLogins = values(sender)
    } else if (actorAccess) {
        actorMode = 'write_access'
    } else if (botSender?.operator === PropertyOperator.IsNotSet) {
        actorMode = 'people'
    }

    return {
        repository: values(repository).length ? values(repository)[0] : null,
        eventTypes: values(eventTypes),
        actorMode,
        actorLogins,
        additional: list.filter((property) => !OWNED_KEYS.has(property?.key)),
    }
}

export function encodeGithubFilters(filters: GithubTriggerFilters): Record<string, any>[] {
    const properties: Record<string, any>[] = []

    if (filters.repository) {
        properties.push(exact('repository', [filters.repository]))
    }

    if (filters.eventTypes.length) {
        properties.push(exact('event_type', filters.eventTypes))
    }

    switch (filters.actorMode) {
        case 'write_access':
            properties.push(exact('actor_access', ['write']))
            break
        case 'people':
            properties.push(presence('bot_sender', PropertyOperator.IsNotSet))
            break
        case 'specific_people':
            properties.push(exact('sender', filters.actorLogins))
            break
        case 'anyone':
            break
    }

    return [...properties, ...filters.additional]
}
