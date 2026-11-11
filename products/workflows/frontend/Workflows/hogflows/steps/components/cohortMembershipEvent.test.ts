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

    const cohortEvent = {
        id: '$cohort_membership_changed',
        type: 'events',
        properties: [
            { key: 'cohort_id', value: 42, operator: 'exact', type: 'event' },
            { key: 'status', value: 'entered', operator: 'exact', type: 'event' },
        ],
    }

    it.each([
        ['a second event', { filters: { events: [cohortEvent, pageviewEntry.filters.events[0]] } }],
        [
            'an extra property filter',
            {
                filters: {
                    events: [
                        {
                            ...cohortEvent,
                            properties: [...cohortEvent.properties, { key: 'plan', value: 'pro', type: 'person' }],
                        },
                    ],
                },
            },
        ],
        [
            'a negated cohort filter',
            {
                filters: {
                    events: [
                        {
                            ...cohortEvent,
                            properties: [
                                { ...cohortEvent.properties[0], operator: 'is_not' },
                                cohortEvent.properties[1],
                            ],
                        },
                    ],
                },
            },
        ],
        [
            'a person-scoped status filter',
            {
                filters: {
                    events: [
                        {
                            ...cohortEvent,
                            properties: [cohortEvent.properties[0], { ...cohortEvent.properties[1], type: 'person' }],
                        },
                    ],
                },
            },
        ],
        [
            'a list of cohort ids',
            {
                filters: {
                    events: [
                        {
                            ...cohortEvent,
                            properties: [{ ...cohortEvent.properties[0], value: [42, 43] }, cohortEvent.properties[1]],
                        },
                    ],
                },
            },
        ],
    ])('leaves an API-written cohort entry with %s among the event entries', (_name, entry) => {
        expect(splitCohortMembershipEntry([entry])).toEqual({ eventEntries: [entry], cohort: null })
    })

    it.each([
        ['clearing the cohort keeps the event entry', [pageviewEntry], [pageviewEntry]],
        ['clearing both stores no entries', [], undefined],
    ])('%s', (_name, eventEntries, expected) => {
        expect(joinCohortMembershipEntry(eventEntries, null)).toEqual(expected)
    })
})
