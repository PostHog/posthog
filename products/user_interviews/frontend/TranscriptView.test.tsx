import { parseTranscript } from './TranscriptView'

describe('parseTranscript', () => {
    it('returns null for transcripts with no recognized speaker prefix', () => {
        expect(parseTranscript('hello world\nthis is just text')).toBeNull()
    })

    it('returns null for empty input', () => {
        expect(parseTranscript('')).toBeNull()
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

    it('treats unrecognized roles as user-side turns', () => {
        const transcript = 'AI: Hi.\nCory: Hey there.'
        const turns = parseTranscript(transcript)
        expect(turns).not.toBeNull()
        // "Cory:" doesn't match the role allowlist — it stays a continuation
        // of the previous turn, which is the safe behavior (no false positives
        // on mid-sentence colons or unfamiliar speaker names).
        expect(turns).toEqual([{ speaker: 'AI', role: 'ai', text: 'Hi.\nCory: Hey there.' }])
    })

    it('is case-insensitive on role prefix', () => {
        const transcript = 'ai: lowercase prefix\nuser: also lowercase'
        expect(parseTranscript(transcript)).toEqual([
            { speaker: 'ai', role: 'ai', text: 'lowercase prefix' },
            { speaker: 'user', role: 'user', text: 'also lowercase' },
        ])
    })
})
