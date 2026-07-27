import { ParsedTranscript, parseTranscript } from './parseTranscript'

const EMPTY: ParsedTranscript = { leadingText: '', turns: [] }

describe('parseTranscript', () => {
    describe.each<[string, string, ParsedTranscript]>([
        ['empty string', '', EMPTY],
        ['no speaker markers falls through to empty', 'Just some prose without any labels at all.', EMPTY],
        [
            'single AI turn',
            'AI: Hello there.',
            { leadingText: '', turns: [{ speaker: 'ai', name: 'AI', text: 'Hello there.' }] },
        ],
        [
            'multi-turn newline-delimited (Vapi format)',
            'AI: Hi.\nUser: Hello.\nAI: How are you?',
            {
                leadingText: '',
                turns: [
                    { speaker: 'ai', name: 'AI', text: 'Hi.' },
                    { speaker: 'user', name: 'User', text: 'Hello.' },
                    { speaker: 'ai', name: 'AI', text: 'How are you?' },
                ],
            },
        ],
        [
            'trailing newline at end of transcript is tolerated',
            'AI: Hi.\nUser: Hello.\n',
            {
                leadingText: '',
                turns: [
                    { speaker: 'ai', name: 'AI', text: 'Hi.' },
                    { speaker: 'user', name: 'User', text: 'Hello.' },
                ],
            },
        ],
        [
            'assistant and interviewee aliases',
            'Assistant: Welcome.\nInterviewee: Thanks.',
            {
                leadingText: '',
                turns: [
                    { speaker: 'ai', name: 'Assistant', text: 'Welcome.' },
                    { speaker: 'user', name: 'Interviewee', text: 'Thanks.' },
                ],
            },
        ],
        [
            'colons in turn body do not split',
            'AI: Pick a number: any number.\nUser: Five.',
            {
                leadingText: '',
                turns: [
                    { speaker: 'ai', name: 'AI', text: 'Pick a number: any number.' },
                    { speaker: 'user', name: 'User', text: 'Five.' },
                ],
            },
        ],
        [
            'speaker keyword mid-turn-body does not split',
            'AI: How did the User: experience feel?\nUser: Good.',
            {
                leadingText: '',
                turns: [
                    { speaker: 'ai', name: 'AI', text: 'How did the User: experience feel?' },
                    { speaker: 'user', name: 'User', text: 'Good.' },
                ],
            },
        ],
        [
            'lowercase prefixes are accepted',
            'ai: Hello.\nuser: Hi.',
            {
                leadingText: '',
                turns: [
                    { speaker: 'ai', name: 'ai', text: 'Hello.' },
                    { speaker: 'user', name: 'user', text: 'Hi.' },
                ],
            },
        ],
        [
            'inline turns on a single line yield one degraded turn (no newline delimiter present)',
            'AI: Hey, Chris. User: Yep. Go ahead.',
            {
                leadingText: '',
                turns: [{ speaker: 'ai', name: 'AI', text: 'Hey, Chris. User: Yep. Go ahead.' }],
            },
        ],
        [
            'leading prose before first speaker prefix is reported (caller falls back to markdown)',
            'Interview started 2026-05-29.\nAI: Hi.\nUser: Hello.',
            {
                leadingText: 'Interview started 2026-05-29.',
                turns: [
                    { speaker: 'ai', name: 'AI', text: 'Hi.' },
                    { speaker: 'user', name: 'User', text: 'Hello.' },
                ],
            },
        ],
    ])('case: %s', (_label, input, expected) => {
        it('parses into the expected shape', () => {
            expect(parseTranscript(input)).toEqual(expected)
        })
    })
})
