import { drawAdventRewards } from './adventDraw'
import { AdventProgress, buildAdventGraph } from './adventGraph'
import { adventToday } from './adventToday'

const REWARDS = drawAdventRewards('0190d8a2-1c4e-7b3a-9f21-5a6b7c8d9e01')

function graphOf(progress: AdventProgress, today: number): ReturnType<typeof buildAdventGraph> {
    return buildAdventGraph(progress, today, REWARDS)
}

describe('buildAdventGraph', () => {
    it('shows both lanes after a question until it is answered, each linked only along itself', () => {
        const graph = graphOf({ opened: [1], answers: {} }, 4)

        expect(graph.doors.filter((door) => door.day === 3).map((door) => door.id)).toEqual([
            'door-3-upper',
            'door-3-lower',
        ])
        expect(graph.links.filter((link) => link.to.startsWith('door-4')).map((link) => [link.from, link.to])).toEqual([
            ['door-3-upper', 'door-4-upper'],
            ['door-3-lower', 'door-4-lower'],
        ])
    })

    it.each([
        ['james', 'upper', 'lower'],
        ['tim', 'lower', 'upper'],
    ])('drops the lane not taken once the person picks %s', (answer, taken, notTaken) => {
        const graph = graphOf({ opened: [1, 2], answers: { 2: answer } }, 4)
        const doorIds = graph.doors.map((door) => door.id)
        const linkEnds = graph.links.flatMap((link) => [link.from, link.to])

        expect(doorIds).toEqual(expect.arrayContaining([`door-3-${taken}`, `door-4-${taken}`]))
        for (const id of [`door-3-${notTaken}`, `door-4-${notTaken}`]) {
            expect(doorIds).not.toContain(id)
            expect(linkEnds).not.toContain(id)
        }
    })

    it('opens doors in order and keeps later days locked by date', () => {
        const graph = graphOf({ opened: [1], answers: {} }, 5)
        const statusOf = (id: string): [string, string | null] | undefined => {
            const door = graph.doors.find((candidate) => candidate.id === id)
            return door && [door.status, door.lockReason]
        }

        expect(statusOf('door-1')).toEqual(['open', null])
        expect(statusOf('door-2')).toEqual(['ready', null])
        expect(statusOf('door-5')).toEqual(['locked', 'order'])
        expect(statusOf('door-6-upper')).toEqual(['locked', 'date'])
    })

    it('locks every door before the first day', () => {
        const graph = graphOf({ opened: [], answers: {} }, 0)

        expect(graph.doors.every((door) => door.status === 'locked' && door.lockReason === 'date')).toBe(true)
    })
})

describe('adventToday', () => {
    it.each([
        ['the end of November', new Date(2026, 10, 30, 23, 59), 0],
        ['the first of December', new Date(2026, 11, 1, 0, 0), 1],
        ['the 13th of December', new Date(2026, 11, 13, 12, 0), 13],
        ['Christmas Eve', new Date(2026, 11, 24, 23, 59), 24],
        ['Boxing Day', new Date(2026, 11, 26, 9, 0), 24],
        ['the next January', new Date(2027, 0, 5, 9, 0), 24],
        ['the December before', new Date(2025, 11, 10, 9, 0), 0],
    ])('unlocks doors by the local date on %s', (_, now, expected) => {
        expect(adventToday(now, { requestedDay: null, canPickDay: false })).toBe(expected)
    })

    it.each([
        ['a staff user picks a day', '7', true, 7],
        ['a staff user picks a day past the end', '30', true, 24],
        ['a staff user picks nonsense', 'soon', true, 5],
        ['a staff user leaves the day blank', '', true, 5],
        ['a staff user leaves only a space as the day', ' ', true, 5],
        ['someone else picks a day', '7', false, 5],
    ])('when %s on 5 December', (_, requestedDay, canPickDay, expected) => {
        expect(adventToday(new Date(2026, 11, 5, 9, 0), { requestedDay, canPickDay })).toBe(expected)
    })
})
