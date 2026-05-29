import { TranscriptTurn, parseTranscript } from './TranscriptChat'

describe('parseTranscript', () => {
    describe.each<[string, string, TranscriptTurn[]]>([
        ['empty string', '', []],
        ['no speaker markers falls through to empty', 'Just some prose without any labels at all.', []],
        ['single AI turn', 'AI: Hello there.', [{ speaker: 'ai', name: 'AI', text: 'Hello there.' }]],
        [
            'AI then User on one line',
            'AI: Hey, Chris. User: Yep. Go ahead.',
            [
                { speaker: 'ai', name: 'AI', text: 'Hey, Chris.' },
                { speaker: 'user', name: 'User', text: 'Yep. Go ahead.' },
            ],
        ],
        [
            'multi-turn with newlines',
            'AI: Hi.\nUser: Hello.\nAI: How are you?',
            [
                { speaker: 'ai', name: 'AI', text: 'Hi.' },
                { speaker: 'user', name: 'User', text: 'Hello.' },
                { speaker: 'ai', name: 'AI', text: 'How are you?' },
            ],
        ],
        [
            'assistant and interviewee aliases',
            'Assistant: Welcome. Interviewee: Thanks.',
            [
                { speaker: 'ai', name: 'Assistant', text: 'Welcome.' },
                { speaker: 'user', name: 'Interviewee', text: 'Thanks.' },
            ],
        ],
        [
            'colons in user content do not split',
            'AI: Pick a number: any number. User: Five.',
            [
                { speaker: 'ai', name: 'AI', text: 'Pick a number: any number.' },
                { speaker: 'user', name: 'User', text: 'Five.' },
            ],
        ],
        ['empty turn is skipped', 'AI:    User: Yep.', [{ speaker: 'user', name: 'User', text: 'Yep.' }]],
    ])('case: %s', (_label, input, expected) => {
        it('parses into the expected turns', () => {
            expect(parseTranscript(input)).toEqual(expected)
        })
    })
})
