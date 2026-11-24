import { parseUsage } from './releaseLaneUsage'

describe('releaseLaneUsage', () => {
    test.each([
        {
            kind: 'flag' as const,
            split: [
                ['true', 30],
                ['false', 10],
                ['', 0],
            ],
            expected: [
                { label: 'Got the feature', users: 30 },
                { label: 'Did not get it', users: 10 },
            ],
        },
        {
            kind: 'survey' as const,
            split: [[40, 12, 5]],
            expected: [
                { label: 'Shown', users: 40 },
                { label: 'Answered', users: 12 },
                { label: 'Dismissed', users: 5 },
            ],
        },
    ])('labels the $kind split and keeps an empty week at zero', ({ kind, split, expected }) => {
        const usage = parseUsage(kind, [['2026-11-20 00:00:00', 7, 19]], [], split)

        expect(usage).toEqual({
            days: [{ day: '2026-11-20', users: 7, total: 19 }],
            weekUsers: 0,
            weekTotal: 0,
            split: expected,
        })
    })
})
