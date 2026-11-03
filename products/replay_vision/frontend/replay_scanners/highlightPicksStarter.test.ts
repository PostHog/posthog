import { planBurst, samplingRateForTarget, starterSpendMode, weeklyVolume } from './highlightPicksStarter'

const recording = (id: string, overrides: Record<string, unknown> = {}): any => ({
    id,
    recording_duration: 120,
    active_seconds: 60,
    ongoing: false,
    ...overrides,
})

describe('highlightPicksStarter', () => {
    const thirty = Array.from({ length: 30 }, (_, i) => recording(`s${i}`))

    it.each<[string, any[], number, 'free' | 'budget', number | null, number | null, number]>([
        ['caps at the burst maximum', thirty, 5, 'free', 2500, null, 25],
        [
            'skips recordings the scan gate refuses',
            [recording('a', { recording_duration: 3 }), recording('b')],
            5,
            'free',
            2500,
            null,
            1,
        ],
        ['leaves a sweep reserve out of the free credits', thirty, 5, 'free', 100, null, 15],
        ['sizes to the budget when paying', thirty, 5, 'budget', 0, 50, 5],
        ['never goes negative', thirty, 5, 'free', 10, null, 0],
        ['uses the maximum when the allowance is unknown', thirty, 5, 'free', null, null, 25],
    ])('%s', (_name, recordings, price, mode, freeLeft, budget, expectedCount) => {
        const plan = planBurst(recordings, price, mode, freeLeft, budget)
        expect(plan.sessionIds).toHaveLength(expectedCount)
        expect(plan.credits).toBe(expectedCount * price)
    })

    it.each<[number | null, number]>([
        [null, 1],
        [120, 1],
        [300, 1],
        [600, 0.5],
        [9000, 0.03],
        [1_000_000, 0.01],
    ])('samples %p a month down to the target', (estimate, rate) => {
        expect(samplingRateForTarget(estimate, 300)).toBe(rate)
    })

    it.each<[number | null, 'free' | 'budget']>([
        [null, 'free'],
        [5, 'free'],
        [4, 'budget'],
        [0, 'budget'],
    ])('needs a budget once %p free credits cannot buy one scan', (freeLeft, mode) => {
        expect(starterSpendMode(freeLeft, 5)).toBe(mode)
    })

    it.each<
        [
            string,
            { matched_sessions_in_window: number; window_days: number } | null,
            number[],
            [number, number | null] | null,
        ]
    >([
        [
            'scales a short window to a week',
            { matched_sessions_in_window: 90, window_days: 3 },
            [120, 240],
            [210, 10.5],
        ],
        ['has no hours without durations', { matched_sessions_in_window: 70, window_days: 7 }, [], [70, null]],
        ['is empty for a team without recordings', { matched_sessions_in_window: 0, window_days: 7 }, [120], null],
        ['is empty before the estimate lands', null, [120], null],
    ])('weekly volume %s', (_name, estimate, durations, expected) => {
        const volume = weeklyVolume(
            estimate,
            durations.map((recording_duration) => ({ recording_duration }))
        )
        if (expected === null) {
            expect(volume).toBeNull()
            return
        }
        expect([volume?.recorded, volume?.hours]).toEqual(expected)
    })
})
