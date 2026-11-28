import { AdventEntryPhase, adventEntryPhase } from './adventEntryPhase'

describe('adventEntryPhase', () => {
    it.each<[string, Date, AdventEntryPhase]>([
        ['the last minute of November', new Date(2026, 10, 30, 23, 59), { status: 'soon' }],
        ['the first of December', new Date(2026, 11, 1, 0, 0), { status: 'open', day: 1 }],
        ['the last minute of December 24', new Date(2026, 11, 24, 23, 59), { status: 'open', day: 24 }],
        ['Christmas Day', new Date(2026, 11, 25, 0, 0), { status: 'over' }],
        ['January', new Date(2027, 0, 5, 9, 0), { status: 'over' }],
    ])('on %s', (_, now, phase) => {
        expect(adventEntryPhase(now)).toEqual(phase)
    })
})
