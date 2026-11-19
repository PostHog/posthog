// PROTOTYPE (throwaway): the type and status tags every entry shows.
import { Badge } from '@posthog/quill'

import { CHANNEL_LABEL, Channel, EntryKind, EntryState, KIND_LABEL, STATE_LABEL } from './prototypeData'

const KIND_VARIANT = { broadcast: 'info', workflow: 'completed', transactional: 'default' } as const
const STATE_VARIANT = {
    draft: 'default',
    scheduled: 'default',
    sending: 'info',
    sent: 'success',
    failed: 'destructive',
    paused: 'warning',
} as const

export function EntryBadges({
    kind,
    state,
    channel,
    repeats,
}: {
    kind: EntryKind
    state?: EntryState
    channel?: Channel
    repeats?: boolean
}): JSX.Element {
    return (
        <span className="inline-flex flex-wrap items-center gap-1">
            <Badge variant={KIND_VARIANT[kind]}>{KIND_LABEL[kind]}</Badge>
            {channel && channel !== 'email' ? <Badge>{CHANNEL_LABEL[channel]}</Badge> : null}
            {repeats ? <Badge>Repeats</Badge> : null}
            {state ? <Badge variant={STATE_VARIANT[state]}>{STATE_LABEL[state]}</Badge> : null}
        </span>
    )
}
