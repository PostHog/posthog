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

export function readCohortMembershipEventEntry(entry: EventEntry | undefined): CohortMembershipEventValue | null {
    const event = entry?.filters?.events?.[0]
    if (event?.id !== COHORT_MEMBERSHIP_CHANGED_EVENT) {
        return null
    }
    const properties: { key?: string; value?: unknown }[] = event.properties ?? []
    const cohortId = Number(properties.find((property) => property.key === 'cohort_id')?.value)
    if (!Number.isInteger(cohortId)) {
        return null
    }
    const status = properties.find((property) => property.key === 'status')?.value
    return { cohortId, transition: status === 'left' ? 'left' : 'entered' }
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
