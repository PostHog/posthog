import { TaskListItemApi, TaskUserBasicInfoApi } from '../generated/api.schemas'

// The same windows as PostHog Desktop, so both apps show the same faces.
/** A face pulses while its person was active this recently: work is happening now. */
export const PRESENCE_LIVE_WINDOW_MS = 3 * 60_000
/** A face stays, without the pulse, this long after its person's last activity. */
export const PRESENCE_RECENT_WINDOW_MS = 2 * 60 * 60_000
/** How many faces a space row shows, so the row stays a glance. */
export const SPACE_PRESENCE_LIMIT = 3

export type PresenceTier = 'live' | 'recent' | 'idle'

/** A future timestamp (clock skew) reads as live. */
export function presenceTier(ts: number, now: number): PresenceTier {
    const age = now - ts
    return age < PRESENCE_LIVE_WINDOW_MS ? 'live' : age < PRESENCE_RECENT_WINDOW_MS ? 'recent' : 'idle'
}

export interface SpacePresence {
    /** The recently active people, most recent first. */
    people: TaskUserBasicInfoApi[]
    /** The uuids of the people in `people` who are working right now. */
    liveUuids: string[]
}

type PresenceTask = Pick<TaskListItemApi, 'created_by' | 'last_activity_at' | 'channel' | 'archived'>

/** What one page of the team's newest tasks says about each space. */
export interface SpaceActivity {
    presence: Record<string, SpacePresence>
    /** When someone last worked in each space. A space with no task on the page has no entry. */
    lastActivityAt: Record<string, string>
}

/** The newest activity in each space, keyed by space id. Archived sessions don't count. */
export function lastActivityBySpace(tasks: readonly PresenceTask[]): Record<string, string> {
    const result: Record<string, string> = {}
    for (const task of tasks) {
        const ts = task.last_activity_at ? Date.parse(task.last_activity_at) : Number.NaN
        if (!task.channel || task.archived || Number.isNaN(ts)) {
            continue
        }
        const current = result[task.channel]
        if (!current || Date.parse(current) < ts) {
            result[task.channel] = task.last_activity_at as string
        }
    }
    return result
}

/**
 * The recently active people in each space, keyed by space id, from one page of the team's tasks.
 * A space with nobody recent has no entry.
 */
export function presenceBySpace(
    tasks: readonly PresenceTask[],
    now: number,
    limit = SPACE_PRESENCE_LIMIT
): Record<string, SpacePresence> {
    const dated = tasks
        .map((task) => ({
            space: task.channel ?? null,
            author: task.archived ? null : (task.created_by ?? null),
            ts: task.last_activity_at ? Date.parse(task.last_activity_at) : Number.NaN,
        }))
        .filter(
            (entry): entry is { space: string; author: TaskUserBasicInfoApi; ts: number } =>
                entry.space !== null && entry.author !== null && !Number.isNaN(entry.ts)
        )
        .sort((first, second) => second.ts - first.ts)

    const result: Record<string, SpacePresence> = {}
    for (const { space, author, ts } of dated) {
        const tier = presenceTier(ts, now)
        if (tier === 'idle') {
            continue
        }
        const entry = (result[space] ??= { people: [], liveUuids: [] })
        if (entry.people.some((person) => person.uuid === author.uuid)) {
            continue
        }
        if (entry.people.length >= limit) {
            continue
        }
        entry.people.push(author)
        // The list is newest first, so a person's first task decides whether they are live.
        if (tier === 'live') {
            entry.liveUuids.push(author.uuid)
        }
    }
    return result
}
