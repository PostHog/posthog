export type TranscriptTurnSpeaker = 'ai' | 'user' | 'other'

export interface TranscriptTurn {
    speaker: TranscriptTurnSpeaker
    name: string
    text: string
}

export interface ParsedTranscript {
    leadingText: string
    turns: TranscriptTurn[]
}

const TURN_SPLIT_RE = /(?:^|\n)\s*(AI|Assistant|Interviewer|User|Interviewee):\s+/i

const AI_SPEAKER_RE = /^(AI|Assistant|Interviewer)$/i
const USER_SPEAKER_RE = /^(User|Interviewee)$/i

export function parseTranscript(transcript: string): ParsedTranscript {
    if (!transcript) {
        return { leadingText: '', turns: [] }
    }
    const parts = transcript.split(TURN_SPLIT_RE)
    if (parts.length < 3) {
        return { leadingText: '', turns: [] }
    }

    const turns: TranscriptTurn[] = []
    for (let i = 1; i < parts.length; i += 2) {
        const name = parts[i]
        const text = (parts[i + 1] ?? '').trim()
        if (!text) {
            continue
        }
        const speaker: TranscriptTurnSpeaker = AI_SPEAKER_RE.test(name)
            ? 'ai'
            : USER_SPEAKER_RE.test(name)
              ? 'user'
              : 'other'
        turns.push({ speaker, name, text })
    }
    return { leadingText: (parts[0] ?? '').trim(), turns }
}
