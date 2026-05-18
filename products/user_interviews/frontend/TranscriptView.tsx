import clsx from 'clsx'

const AI_ROLES = ['AI', 'Assistant', 'Bot', 'Agent', 'System', 'Researcher', 'Interviewer'] as const
const USER_ROLES = ['User', 'Customer', 'Interviewee', 'Respondent', 'Participant'] as const
const ALL_ROLES = [...AI_ROLES, ...USER_ROLES]
const SPEAKER_RE = new RegExp(`^(${ALL_ROLES.join('|')})\\s*:\\s*(.*)$`, 'i')
const AI_ROLE_SET = new Set(AI_ROLES.map((r) => r.toLowerCase()))

export interface TranscriptTurn {
    speaker: string
    role: 'ai' | 'user'
    text: string
}

// Parse a Vapi-style transcript into speaker turns. Returns null if no
// recognized speaker prefixes are present, so the caller can fall back to
// preserving raw whitespace instead of inventing turn boundaries.
export function parseTranscript(text: string): TranscriptTurn[] | null {
    const turns: TranscriptTurn[] = []
    let sawPrefix = false

    for (const rawLine of text.split('\n')) {
        const line = rawLine.replace(/\s+$/u, '')
        const match = line.match(SPEAKER_RE)
        if (match) {
            sawPrefix = true
            const speaker = match[1]
            const body = match[2]
            turns.push({
                speaker,
                role: AI_ROLE_SET.has(speaker.toLowerCase()) ? 'ai' : 'user',
                text: body,
            })
        } else if (turns.length > 0) {
            turns[turns.length - 1].text += '\n' + line
        } else if (line.trim()) {
            turns.push({ speaker: '', role: 'user', text: line })
        }
    }

    if (!sawPrefix) {
        return null
    }

    for (const turn of turns) {
        turn.text = turn.text.replace(/^\n+|\n+$/g, '')
    }
    return turns
}

export function TranscriptView({ transcript }: { transcript: string }): JSX.Element {
    const turns = parseTranscript(transcript)

    if (!turns) {
        return <div className="text-sm leading-relaxed whitespace-pre-wrap">{transcript}</div>
    }

    return (
        <div className="flex flex-col gap-3">
            {turns.map((turn, i) => (
                <div
                    key={i}
                    className={clsx(
                        'rounded-md p-3 border',
                        turn.role === 'ai' ? 'bg-bg-light border-border' : 'bg-primary-highlight border-primary'
                    )}
                >
                    {turn.speaker && (
                        <div className="text-xs font-semibold uppercase tracking-wide text-muted mb-1">
                            {turn.speaker}
                        </div>
                    )}
                    <div className="text-sm leading-relaxed whitespace-pre-wrap">{turn.text}</div>
                </div>
            ))}
        </div>
    )
}
