import { workflowEventsFromFilters } from './messagingDestinations'

describe('workflowEventsFromFilters', () => {
    it.each([
        ['drops the $identify and $pageview defaults', [{ id: '$identify' }, { id: '$pageview' }], []],
        [
            'keeps custom events once, in order',
            [{ id: 'signed_up' }, { id: '$pageview' }, { id: 'signed_up' }],
            ['signed_up'],
        ],
        [
            'caps the list at what the build endpoint accepts',
            ['a', 'b', 'c', 'd', 'e', 'f'].map((id) => ({ id })),
            ['a', 'b', 'c', 'd', 'e'],
        ],
        ['ignores an "any event" filter without a name', [{ id: null }], []],
    ])('%s', (_label, events, expected) => {
        expect(workflowEventsFromFilters({ events })).toEqual(expected)
    })
})
