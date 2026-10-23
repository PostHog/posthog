import { joinCohortMembershipEntry, splitCohortMembershipEntry } from './cohortMembershipEvent'

describe('cohortMembershipEvent', () => {
    const pageviewEntry = { filters: { events: [{ id: '$pageview', name: '$pageview', type: 'events' }] } }

    it.each([
        ['a join next to an event entry', [pageviewEntry], { cohortId: 42, transition: 'entered' as const }],
        ['a leave on its own', [], { cohortId: 7, transition: 'left' as const }],
    ])('reads back %s', (_name, eventEntries, cohort) => {
        const stored = joinCohortMembershipEntry(eventEntries, cohort)

        expect(splitCohortMembershipEntry(stored)).toEqual({ eventEntries, cohort })
    })

    it.each([
        ['clearing the cohort keeps the event entry', [pageviewEntry], [pageviewEntry]],
        ['clearing both stores no entries', [], undefined],
    ])('%s', (_name, eventEntries, expected) => {
        expect(joinCohortMembershipEntry(eventEntries, null)).toEqual(expected)
    })
})
