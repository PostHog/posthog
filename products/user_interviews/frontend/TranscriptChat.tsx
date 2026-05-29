import clsx from 'clsx'
import { useMemo } from 'react'

import { ProfilePicture } from '@posthog/lemon-ui'

import { RobotHog } from 'lib/components/hedgehogs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { PersonType } from '~/types'

export type TranscriptTurnSpeaker = 'ai' | 'user' | 'other'

export interface TranscriptTurn {
    speaker: TranscriptTurnSpeaker
    name: string
    text: string
}

const TURN_SPLIT_RE = /\b(AI|Assistant|Interviewer|User|Interviewee):\s+/

const AI_SPEAKER_RE = /^(AI|Assistant|Interviewer)$/i
const USER_SPEAKER_RE = /^(User|Interviewee)$/i

export function parseTranscript(transcript: string): TranscriptTurn[] {
    if (!transcript) {
        return []
    }
    const parts = transcript.split(TURN_SPLIT_RE)
    if (parts.length < 3) {
        return []
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
    return turns
}

interface TranscriptChatProps {
    transcript: string
    person: PersonType | null
    identifier: string
}

export function TranscriptChat({ transcript, person, identifier }: TranscriptChatProps): JSX.Element {
    const turns = useMemo(() => parseTranscript(transcript), [transcript])

    if (turns.length === 0) {
        return <LemonMarkdown className="text-sm leading-relaxed">{transcript}</LemonMarkdown>
    }

    return (
        <div className="flex flex-col gap-3">
            {turns.map((turn, index) => (
                <TranscriptBubble key={index} turn={turn} person={person} identifier={identifier} />
            ))}
        </div>
    )
}

interface TranscriptBubbleProps {
    turn: TranscriptTurn
    person: PersonType | null
    identifier: string
}

function TranscriptBubble({ turn, person, identifier }: TranscriptBubbleProps): JSX.Element {
    const isUser = turn.speaker === 'user'
    return (
        <div className={clsx('flex items-start gap-2', isUser ? 'flex-row-reverse' : 'flex-row')}>
            <div className="shrink-0">
                <TranscriptAvatar turn={turn} person={person} identifier={identifier} />
            </div>
            <div
                className={clsx(
                    'rounded-lg border px-3 py-2 max-w-[85%] min-w-0',
                    isUser ? 'bg-accent-highlight-secondary' : 'bg-surface-primary'
                )}
            >
                <div className="text-xs font-semibold mb-1 text-muted">{labelFor(turn, person, identifier)}</div>
                <LemonMarkdown className="text-sm">{turn.text}</LemonMarkdown>
            </div>
        </div>
    )
}

function TranscriptAvatar({ turn, person, identifier }: TranscriptBubbleProps): JSX.Element {
    if (turn.speaker === 'ai') {
        return (
            <span
                className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-surface-tertiary overflow-hidden"
                title="AI interviewer"
            >
                <RobotHog className="w-8 h-8 object-cover" />
            </span>
        )
    }

    if (turn.speaker === 'user') {
        const email = person?.properties?.email ?? (identifier.includes('@') ? identifier : undefined)
        const name = person?.properties?.name ?? person?.name ?? identifier
        return <ProfilePicture user={{ email, first_name: name }} name={name} size="md" />
    }

    return <ProfilePicture name={turn.name} size="md" />
}

function labelFor(turn: TranscriptTurn, person: PersonType | null, identifier: string): string {
    if (turn.speaker === 'ai') {
        return 'AI interviewer'
    }
    if (turn.speaker === 'user') {
        return person?.properties?.name || person?.properties?.email || person?.name || identifier
    }
    return turn.name
}
