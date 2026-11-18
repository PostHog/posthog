import { TaskUserBasicInfoApi } from '../generated/api.schemas'
import { lastActivityBySpace, presenceBySpace } from './spacePresence'

const NOW = Date.parse('2026-09-28T18:30:00Z')

const person = (uuid: string): TaskUserBasicInfoApi => ({
    id: uuid.length,
    uuid,
    distinct_id: uuid,
    first_name: uuid,
    last_name: '',
    email: `${uuid}@example.com`,
})

const task = (
    author: string | null,
    minutesAgo: number,
    channel: string | null = 'space-a',
    archived = false
): Parameters<typeof presenceBySpace>[0][number] => ({
    created_by: author ? person(author) : null,
    last_activity_at: new Date(NOW - minutesAgo * 60_000).toISOString(),
    channel,
    archived,
})

describe('spacePresence', () => {
    test.each([
        {
            name: 'orders people newest first and marks only those active in the last 3 minutes as live',
            tasks: [task('ada', 30), task('grace', 1)],
            expected: { 'space-a': { people: ['grace', 'ada'], liveUuids: ['grace'] } },
        },
        {
            name: 'decides a person is live from their newest task, and lists them once',
            tasks: [task('ada', 50), task('ada', 2), task('ada', 10)],
            expected: { 'space-a': { people: ['ada'], liveUuids: ['ada'] } },
        },
        {
            name: 'keeps the three freshest people and never marks a dropped person live',
            tasks: [task('a', 10), task('b', 20), task('c', 30), task('d', 40), task('d', 1)],
            expected: { 'space-a': { people: ['d', 'a', 'b'], liveUuids: ['d'] } },
        },
        {
            name: 'drops activity older than two hours, archived sessions, and sessions without a space or author',
            tasks: [task('old', 121), task('gone', 1, 'space-a', true), task('loose', 1, null), task(null, 1)],
            expected: {},
        },
        {
            name: 'keeps each space separate',
            tasks: [task('ada', 5, 'space-a'), task('grace', 5, 'space-b')],
            expected: {
                'space-a': { people: ['ada'], liveUuids: [] },
                'space-b': { people: ['grace'], liveUuids: [] },
            },
        },
    ])('presenceBySpace $name', ({ tasks, expected }) => {
        const result = presenceBySpace(tasks, NOW)
        const simplified = Object.fromEntries(
            Object.entries(result).map(([space, presence]) => [
                space,
                { people: presence.people.map((p) => p.uuid), liveUuids: presence.liveUuids },
            ])
        )
        expect(simplified).toEqual(expected)
    })

    test.each([
        {
            name: 'keeps the newest activity per space, whatever the page order',
            tasks: [task('ada', 300), task('grace', 5), task('ada', 60, 'space-b')],
            expected: { 'space-a': 5, 'space-b': 60 },
        },
        {
            name: 'counts old activity and tasks without an author, but not archived or loose tasks',
            tasks: [task(null, 600), task('gone', 1, 'space-a', true), task('loose', 1, null)],
            expected: { 'space-a': 600 },
        },
    ])('lastActivityBySpace $name', ({ tasks, expected }) => {
        const minutesAgo = Object.fromEntries(
            Object.entries(lastActivityBySpace(tasks)).map(([space, at]) => [space, (NOW - Date.parse(at)) / 60_000])
        )
        expect(minutesAgo).toEqual(expected)
    })
})
