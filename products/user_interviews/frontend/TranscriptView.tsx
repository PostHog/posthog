import clsx from 'clsx'

const AI_ROLES = ['AI', 'Assistant', 'Bot', 'Agent', 'System', 'Researcher', 'Interviewer'] as const
const AI_ROLE_SET = new Set(AI_ROLES.map((r) => r.toLowerCase()))

// Bounded length (≤30 chars) keeps the regex from over-matching on
// mid-sentence prose like "Note: actually...". The cap is generous enough
// to fit display names ("Cory Slater") or short titles ("Acme Customer").
const SPEAKER_PREFIX_RE = /^([A-Za-z][A-Za-z0-9 ._'-]{0,29}?)\s*:\s+(.*)$/

export interface TranscriptTurn {
    speaker: string
    role: 'ai' | 'user'
    text: string
}

// Parse a transcript into speaker turns. Detects any consistent
// "<Speaker>: <text>" prefix pattern (not just a fixed allowlist) so
// transcripts that use real participant names alongside an AI label still
// split correctly. The AI vs user classification still uses an allowlist
// of canonical AI labels — anything else falls into the user bucket.
// Returns null when the transcript has no detectable turn structure so the
// caller can fall back to raw pre-wrapped text instead of inventing speakers.
export function parseTranscript(text: string): TranscriptTurn[] | null {
    const lines = text.split('\n').map((l) => l.replace(/\s+$/u, ''))

    // Require at least two prefixed lines so a single incidental "Note: ..."
    // doesn't trip the parser into turn-rendering mode for free-form notes.
    const prefixedLineCount = lines.filter((l) => SPEAKER_PREFIX_RE.test(l)).length
    if (prefixedLineCount < 2) {
        return null
    }

    const turns: TranscriptTurn[] = []
    for (const line of lines) {
        const match = line.match(SPEAKER_PREFIX_RE)
        if (match) {
            const speaker = match[1].trim()
            turns.push({
                speaker,
                role: AI_ROLE_SET.has(speaker.toLowerCase()) ? 'ai' : 'user',
                text: match[2],
            })
        } else if (turns.length > 0 && line.trim()) {
            turns[turns.length - 1].text += '\n' + line
        }
        // Preamble lines before the first turn are dropped — Vapi transcripts
        // don't include them, and rendering them as an unattributed styled
        // bubble was a worse failure mode than just omitting them.
    }

    return turns.length > 0 ? turns : null
}

export function TranscriptView({ transcript }: { transcript: string }): JSX.Element {
    const turns = parseTranscript(transcript)

    if (!turns) {
        return <div className="text-sm leading-relaxed whitespace-pre-wrap">{transcript}</div>
    }

    return (
        <div className="flex flex-col gap-3">
            {turns.map((turn, i) => (
                <article
                    key={i}
                    aria-label={`Turn ${i + 1}${turn.speaker ? ` — ${turn.speaker}` : ''}`}
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
                </article>
            ))}
        </div>
    )
}
