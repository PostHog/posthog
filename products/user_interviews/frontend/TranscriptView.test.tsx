import { render } from '@testing-library/react'

import { TranscriptTurn, TranscriptView, parseTranscript } from './TranscriptView'

describe('parseTranscript', () => {
    it.each<[string, string]>([
        ['empty input', ''],
        ['plain text without speaker prefixes', 'hello world\nthis is just text'],
        // One prefixed line is below the two-line floor — guards against turning ordinary
        // prose with one incidental colon into a turn-rendered view.
        ['a single incidental "Note:" prefix', 'Note: this is a free-form note\nwith no other structure'],
    ])('returns null for %s', (_label, transcript) => {
        expect(parseTranscript(transcript)).toBeNull()
    })

    it.each<[string, string, TranscriptTurn[]]>([
        [
            'a Vapi-style AI/User transcript',
            'AI: Hi, thanks for joining.\nUser: No problem.\nAI: Great.',
            [
                { speaker: 'AI', role: 'ai', text: 'Hi, thanks for joining.' },
                { speaker: 'User', role: 'user', text: 'No problem.' },
                { speaker: 'AI', role: 'ai', text: 'Great.' },
            ],
        ],
        [
            'Assistant and Interviewee as alternative role names',
            'Assistant: Question one?\nInterviewee: My answer.',
            [
                { speaker: 'Assistant', role: 'ai', text: 'Question one?' },
                { speaker: 'Interviewee', role: 'user', text: 'My answer.' },
            ],
        ],
        [
            'continuation lines without a prefix attached to the current turn',
            'AI: Line one.\nLine two of the same turn.\nUser: Reply.',
            [
                { speaker: 'AI', role: 'ai', text: 'Line one.\nLine two of the same turn.' },
                { speaker: 'User', role: 'user', text: 'Reply.' },
            ],
        ],
        [
            // Real-name participants must not be glued onto the prior AI turn.
            'unknown speaker names as separate user-side turns (no AI misattribution)',
            'AI: Hi.\nCory: Hey there.\nAI: How are you?\nCory: Doing well.',
            [
                { speaker: 'AI', role: 'ai', text: 'Hi.' },
                { speaker: 'Cory', role: 'user', text: 'Hey there.' },
                { speaker: 'AI', role: 'ai', text: 'How are you?' },
                { speaker: 'Cory', role: 'user', text: 'Doing well.' },
            ],
        ],
        [
            'case-insensitive AI role classification',
            'ai: lowercase prefix\nuser: also lowercase',
            [
                { speaker: 'ai', role: 'ai', text: 'lowercase prefix' },
                { speaker: 'user', role: 'user', text: 'also lowercase' },
            ],
        ],
        [
            'CRLF line endings',
            'AI: hi\r\nUser: hello\r\n',
            [
                { speaker: 'AI', role: 'ai', text: 'hi' },
                { speaker: 'User', role: 'user', text: 'hello' },
            ],
        ],
        [
            'leading preamble dropped before the first prefixed turn',
            'Call started at 10:00\nAI: Hi\nUser: Hello',
            [
                { speaker: 'AI', role: 'ai', text: 'Hi' },
                { speaker: 'User', role: 'user', text: 'Hello' },
            ],
        ],
        [
            'blank lines between turns ignored',
            'AI: First\n\nUser: Second\n\nAI: Third',
            [
                { speaker: 'AI', role: 'ai', text: 'First' },
                { speaker: 'User', role: 'user', text: 'Second' },
                { speaker: 'AI', role: 'ai', text: 'Third' },
            ],
        ],
    ])('parses %s', (_label, transcript, expected) => {
        expect(parseTranscript(transcript)).toEqual(expected)
    })
})

describe('TranscriptView', () => {
    it('renders raw pre-wrapped text when no turn structure is detected', () => {
        const { container } = render(<TranscriptView transcript="just some free-form notes" />)
        expect(container.textContent).toBe('just some free-form notes')
        expect(container.querySelector('.whitespace-pre-wrap')).not.toBeNull()
    })

    it('renders one card per parsed turn with the speaker label', () => {
        const { container, getAllByRole } = render(<TranscriptView transcript={'AI: Hi\nUser: Hello'} />)
        const turns = getAllByRole('article')
        expect(turns).toHaveLength(2)
        expect(container.textContent).toContain('AI')
        expect(container.textContent).toContain('Hi')
        expect(container.textContent).toContain('User')
        expect(container.textContent).toContain('Hello')
    })
})
