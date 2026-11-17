// PROTOTYPE (ticket #385), throwaway. One landing session: where it landed, how long, what it led to, and Watch.
import { IconPlayFilled } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import { NO_RECORDING_TEXT, whoText } from './journeyCopy'
import type { JourneyData, JourneySession } from './journeyFixtures'

export function JourneySessionSummary({
    session,
    data,
    onWatch,
}: {
    session: JourneySession
    data: JourneyData
    onWatch: (session: JourneySession) => void
}): JSX.Element {
    const who = whoText(session, data)
    const outcomes = session.events.filter((event) => event.outcome)
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                <span>
                    Landed on <code className="text-xs">{session.landing.split('?')[0]}</code>
                </span>
                <span className="text-secondary">
                    <TZLabel time={session.startedAt} formatDate="MMM D" formatTime="HH:mm" />
                </span>
                <span className="text-secondary">
                    · {humanFriendlyDuration(session.durationSeconds)} · {session.pages} pages · {session.device}
                </span>
            </div>
            {outcomes.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    <span className="text-xs text-secondary">Led to</span>
                    {outcomes.map((event) => (
                        <Link
                            key={event.at}
                            to={urls.event(`proto-${session.id}-${event.label}`, event.at, event.label)}
                            data-attr="prototype-journey-outcome-event"
                        >
                            <LemonTag type="success">{event.label}</LemonTag>
                        </Link>
                    ))}
                </div>
            )}
            {who && (
                <div className="flex flex-wrap items-center gap-1 text-xs">
                    <LemonTag type={session.who === 'someone-else' ? 'warning' : 'muted'}>
                        {session.who === 'someone-else' ? 'Someone else' : 'No person'}
                    </LemonTag>
                    <span className="text-secondary">{who}</span>
                </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
                {session.recording ? (
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconPlayFilled />}
                        onClick={() => onWatch(session)}
                        data-attr="prototype-journey-watch"
                    >
                        Watch from landing
                    </LemonButton>
                ) : (
                    <>
                        <span className="text-xs text-secondary">{NO_RECORDING_TEXT}</span>
                        <LemonButton type="secondary" size="xsmall" to={urls.replaySettings()}>
                            Turn on session replay
                        </LemonButton>
                    </>
                )}
            </div>
        </div>
    )
}
