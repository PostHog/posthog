import clsx from 'clsx'

import * as roboHogPng from '@posthog/brand/hoggies/png/robo-hog'

import { pngHoggie } from 'lib/brand/hoggies'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { asDisplay } from 'scenes/persons/person-utils'
import { PersonIcon } from 'scenes/persons/PersonDisplay'

import { PersonType } from '~/types'

import { TranscriptTurn, parseTranscript } from './parseTranscript'

const HedgehogRoboHog = pngHoggie(roboHogPng)

interface TranscriptChatProps {
    transcript: string
    person: PersonType | null
    identifier: string
}

export function TranscriptChat({ transcript, person, identifier }: TranscriptChatProps): JSX.Element {
    const { leadingText, turns } = parseTranscript(transcript)

    if (turns.length === 0 || leadingText) {
        return (
            <div data-attr="transcript-chat" data-parsed="false">
                <LemonMarkdown className="text-sm leading-relaxed">{transcript}</LemonMarkdown>
            </div>
        )
    }

    return (
        <div data-attr="transcript-chat" data-parsed="true" className="flex flex-col gap-3">
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
                title={turn.name}
            >
                <HedgehogRoboHog className="w-8 h-8 object-cover" />
            </span>
        )
    }

    if (turn.speaker === 'user') {
        return <PersonIcon person={effectivePerson(person, identifier)} size="md" />
    }

    return <PersonIcon displayName={turn.name} size="md" />
}

function labelFor(turn: TranscriptTurn, person: PersonType | null, identifier: string): string {
    if (turn.speaker === 'user') {
        return asDisplay(effectivePerson(person, identifier))
    }
    return turn.name
}

function effectivePerson(person: PersonType | null, identifier: string): PersonType {
    return person ?? { distinct_ids: [identifier], properties: {} }
}
