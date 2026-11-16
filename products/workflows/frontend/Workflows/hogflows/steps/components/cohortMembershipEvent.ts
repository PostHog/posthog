// pinned: the subscription matcher builds this event from realtime cohort membership changes.
// Renaming it breaks every saved conversion goal and wait step that uses a cohort.
export const COHORT_MEMBERSHIP_CHANGED_EVENT = '$cohort_membership_changed'

export type CohortTransition = 'entered' | 'left'

export interface CohortMembershipEventValue {
    cohortId: number
    transition: CohortTransition
}

export interface EventEntry {
    filters?: any
    name?: string
}

export function cohortMembershipEventEntry({ cohortId, transition }: CohortMembershipEventValue): EventEntry {
    return {
        filters: {
            events: [
                {
                    id: COHORT_MEMBERSHIP_CHANGED_EVENT,
                    name: COHORT_MEMBERSHIP_CHANGED_EVENT,
                    type: 'events',
                    order: 0,
                    properties: [
                        { key: 'cohort_id', value: cohortId, operator: 'exact', type: 'event' },
                        { key: 'status', value: transition, operator: 'exact', type: 'event' },
                    ],
                },
            ],
        },
    }
}

/**
 * Reads an entry only when it has exactly the shape the picker writes. Any other entry, for example one
 * written through the API with a second event or an extra filter, stays with the event filters, so that
 * saving from the picker cannot drop what it does not show.
 */
export function readCohortMembershipEventEntry(entry: EventEntry | undefined): CohortMembershipEventValue | null {
    const filters = entry?.filters
    const events = filters?.events ?? []
    if (events.length !== 1 || filters?.actions?.length || filters?.properties?.length) {
        return null
    }
    const [event] = events
    const properties: { key?: string; value?: unknown; operator?: string; type?: string }[] = event?.properties ?? []
    if (event?.id !== COHORT_MEMBERSHIP_CHANGED_EVENT || properties.length !== 2) {
        return null
    }
    // Rewriting a negated or person-scoped filter as an exact event match would change what the goal matches.
    if (properties.some((property) => property.operator !== 'exact' || property.type !== 'event')) {
        return null
    }
    const cohortValue = properties.find((property) => property.key === 'cohort_id')?.value
    const cohortId = typeof cohortValue === 'number' || typeof cohortValue === 'string' ? Number(cohortValue) : NaN
    const status = properties.find((property) => property.key === 'status')?.value
    if (!Number.isInteger(cohortId) || (status !== 'entered' && status !== 'left')) {
        return null
    }
    return { cohortId, transition: status }
}

/** Separates the cohort entry from the ordinary event entries, so each editor section changes only its own. */
export function splitCohortMembershipEntry(entries: EventEntry[] | null | undefined): {
    eventEntries: EventEntry[]
    cohort: CohortMembershipEventValue | null
} {
    const eventEntries: EventEntry[] = []
    let cohort: CohortMembershipEventValue | null = null
    for (const entry of entries ?? []) {
        const read: CohortMembershipEventValue | null = cohort ? null : readCohortMembershipEventEntry(entry)
        if (read) {
            cohort = read
        } else {
            eventEntries.push(entry)
        }
    }
    return { eventEntries, cohort }
}

export function joinCohortMembershipEntry(
    eventEntries: EventEntry[],
    cohort: CohortMembershipEventValue | null
): EventEntry[] | undefined {
    const entries = cohort ? [...eventEntries, cohortMembershipEventEntry(cohort)] : eventEntries
    return entries.length ? entries : undefined
}
