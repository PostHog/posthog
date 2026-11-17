// PROTOTYPE (ticket #385), throwaway. Stands in for the real recording player, which needs a recorded session.
import { IconPlayFilled } from '@posthog/icons'
import { LemonModal } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { JourneySession } from './journeyFixtures'

export function JourneyRecordingModal({
    session,
    onClose,
}: {
    session: JourneySession | null
    onClose: () => void
}): JSX.Element {
    return (
        <LemonModal
            isOpen={!!session}
            onClose={onClose}
            title={session ? `Session on ${session.landing.split('?')[0]}` : ''}
            description="Prototype: the real page opens the recording player here, at the moment the visitor landed."
            width={880}
        >
            {session && (
                <div className="flex flex-col gap-3">
                    <div className="aspect-video bg-surface-tertiary rounded flex flex-col items-center justify-center gap-2 text-secondary">
                        <IconPlayFilled className="text-5xl" />
                        <span className="text-sm">
                            {session.device} · {humanFriendlyDuration(session.durationSeconds)}
                        </span>
                    </div>
                    <ol className="m-0 p-0 list-none flex flex-col gap-1">
                        {session.events.map((event) => (
                            <li key={event.at + event.label} className="flex gap-3 text-sm">
                                <span className="text-secondary w-20 shrink-0">
                                    <TZLabel time={event.at} formatDate="MMM D" formatTime="HH:mm:ss" />
                                </span>
                                <span className={event.outcome ? 'font-semibold' : undefined}>{event.label}</span>
                            </li>
                        ))}
                    </ol>
                </div>
            )}
        </LemonModal>
    )
}
