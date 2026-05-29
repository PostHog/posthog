import { TranscriptTurn, parseTranscript } from './TranscriptChat'

describe('parseTranscript', () => {
    describe.each<[string, string, TranscriptTurn[]]>([
        ['empty string', '', []],
        ['no speaker markers falls through to empty', 'Just some prose without any labels at all.', []],
        ['single AI turn', 'AI: Hello there.', [{ speaker: 'ai', name: 'AI', text: 'Hello there.' }]],
        [
            'multi-turn newline-delimited (Vapi format)',
            'AI: Hi.\nUser: Hello.\nAI: How are you?',
            [
                { speaker: 'ai', name: 'AI', text: 'Hi.' },
                { speaker: 'user', name: 'User', text: 'Hello.' },
                { speaker: 'ai', name: 'AI', text: 'How are you?' },
            ],
        ],
        [
            'trailing newline at end of transcript is tolerated',
            'AI: Hi.\nUser: Hello.\n',
            [
                { speaker: 'ai', name: 'AI', text: 'Hi.' },
                { speaker: 'user', name: 'User', text: 'Hello.' },
            ],
        ],
        [
            'assistant and interviewee aliases',
            'Assistant: Welcome.\nInterviewee: Thanks.',
            [
                { speaker: 'ai', name: 'Assistant', text: 'Welcome.' },
                { speaker: 'user', name: 'Interviewee', text: 'Thanks.' },
            ],
        ],
        [
            'colons in turn body do not split',
            'AI: Pick a number: any number.\nUser: Five.',
            [
                { speaker: 'ai', name: 'AI', text: 'Pick a number: any number.' },
                { speaker: 'user', name: 'User', text: 'Five.' },
            ],
        ],
        [
            'speaker keyword mid-turn-body does not split',
            'AI: How did the User: experience feel?\nUser: Good.',
            [
                { speaker: 'ai', name: 'AI', text: 'How did the User: experience feel?' },
                { speaker: 'user', name: 'User', text: 'Good.' },
            ],
        ],
        [
            'lowercase prefixes are accepted',
            'ai: Hello.\nuser: Hi.',
            [
                { speaker: 'ai', name: 'ai', text: 'Hello.' },
                { speaker: 'user', name: 'user', text: 'Hi.' },
            ],
        ],
        [
            'inline turns on a single line yield one degraded turn (no newline delimiter present)',
            'AI: Hey, Chris. User: Yep. Go ahead.',
            [{ speaker: 'ai', name: 'AI', text: 'Hey, Chris. User: Yep. Go ahead.' }],
        ],
    ])('case: %s', (_label, input, expected) => {
        it('parses into the expected turns', () => {
            expect(parseTranscript(input)).toEqual(expected)
        })
    })
})
