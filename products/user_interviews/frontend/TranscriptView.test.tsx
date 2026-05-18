import { render } from '@testing-library/react'

import { TranscriptView, parseTranscript } from './TranscriptView'

describe('parseTranscript', () => {
    it('returns null for transcripts with no recognized speaker prefix', () => {
        expect(parseTranscript('hello world\nthis is just text')).toBeNull()
    })

    it('returns null for empty input', () => {
        expect(parseTranscript('')).toBeNull()
    })

    it('returns null for a single incidental prefix like "Note: ..."', () => {
        // One prefixed line is below the two-line floor — guards against
        // turning ordinary prose with one colon into a turn-rendered view.
        expect(parseTranscript('Note: this is a free-form note\nwith no other structure')).toBeNull()
    })

    it('splits a Vapi-style AI/User transcript into turns', () => {
        const transcript = 'AI: Hi, thanks for joining.\nUser: No problem.\nAI: Great.'
        expect(parseTranscript(transcript)).toEqual([
            { speaker: 'AI', role: 'ai', text: 'Hi, thanks for joining.' },
            { speaker: 'User', role: 'user', text: 'No problem.' },
            { speaker: 'AI', role: 'ai', text: 'Great.' },
        ])
    })

    it('recognizes Assistant and Interviewee as alternative role names', () => {
        const transcript = 'Assistant: Question one?\nInterviewee: My answer.'
        expect(parseTranscript(transcript)).toEqual([
            { speaker: 'Assistant', role: 'ai', text: 'Question one?' },
            { speaker: 'Interviewee', role: 'user', text: 'My answer.' },
        ])
    })

    it('attaches continuation lines without a prefix to the current turn', () => {
        const transcript = 'AI: Line one.\nLine two of the same turn.\nUser: Reply.'
        expect(parseTranscript(transcript)).toEqual([
            { speaker: 'AI', role: 'ai', text: 'Line one.\nLine two of the same turn.' },
            { speaker: 'User', role: 'user', text: 'Reply.' },
        ])
    })

    it('treats unknown speaker names as separate user-side turns (no AI misattribution)', () => {
        // Real-name participants must not be glued onto the prior AI turn.
        const transcript = 'AI: Hi.\nCory: Hey there.\nAI: How are you?\nCory: Doing well.'
        expect(parseTranscript(transcript)).toEqual([
            { speaker: 'AI', role: 'ai', text: 'Hi.' },
            { speaker: 'Cory', role: 'user', text: 'Hey there.' },
            { speaker: 'AI', role: 'ai', text: 'How are you?' },
            { speaker: 'Cory', role: 'user', text: 'Doing well.' },
        ])
    })

    it('is case-insensitive when classifying AI roles', () => {
        const transcript = 'ai: lowercase prefix\nuser: also lowercase'
        expect(parseTranscript(transcript)).toEqual([
            { speaker: 'ai', role: 'ai', text: 'lowercase prefix' },
            { speaker: 'user', role: 'user', text: 'also lowercase' },
        ])
    })

    it('handles CRLF line endings', () => {
        const transcript = 'AI: hi\r\nUser: hello\r\n'
        expect(parseTranscript(transcript)).toEqual([
            { speaker: 'AI', role: 'ai', text: 'hi' },
            { speaker: 'User', role: 'user', text: 'hello' },
        ])
    })

    it('drops leading preamble before the first prefixed turn', () => {
        const transcript = 'Call started at 10:00\nAI: Hi\nUser: Hello'
        expect(parseTranscript(transcript)).toEqual([
            { speaker: 'AI', role: 'ai', text: 'Hi' },
            { speaker: 'User', role: 'user', text: 'Hello' },
        ])
    })

    it('ignores blank lines between turns', () => {
        const transcript = 'AI: First\n\nUser: Second\n\nAI: Third'
        expect(parseTranscript(transcript)).toEqual([
            { speaker: 'AI', role: 'ai', text: 'First' },
            { speaker: 'User', role: 'user', text: 'Second' },
            { speaker: 'AI', role: 'ai', text: 'Third' },
        ])
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
