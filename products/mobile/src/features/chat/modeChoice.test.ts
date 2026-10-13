import { initialModeChoice, type ModeChoice, type ModeChoiceAction, modeChoiceReducer } from './modeChoice'

function run(...actions: ModeChoiceAction[]): ModeChoice {
    return actions.reduce(modeChoiceReducer, initialModeChoice)
}

describe('mode choice', () => {
    test.each<[string, ModeChoiceAction[], ModeChoice]>([
        [
            'a pick goes out with one message, and the chip keeps it',
            [{ type: 'picked', mode: 'sql' }, { type: 'sent' }],
            { shown: 'sql', pending: null, picked: true },
        ],
        [
            'a stored mode labels the chip but is never sent',
            [{ type: 'seeded', mode: 'error_tracking' }],
            { shown: 'error_tracking', pending: null, picked: false },
        ],
        [
            'a stored mode that loads after a pick does not replace it',
            [
                { type: 'picked', mode: 'sql' },
                { type: 'seeded', mode: 'error_tracking' },
            ],
            { shown: 'sql', pending: 'sql', picked: true },
        ],
        [
            'new chat goes back to Auto with nothing to send',
            [{ type: 'picked', mode: 'sql' }, { type: 'reset' }],
            initialModeChoice,
        ],
    ])('%s', (_name, actions, expected) => {
        expect(run(...actions)).toEqual(expected)
    })
})
