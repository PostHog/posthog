import { humanFriendlyDuration } from 'lib/utils/durations'

import { SessionRecordingType } from '~/types'

import { IneligibleKind, ineligibleKindLabel } from '../replay_scanners/types'

// Mirror: keep in sync with products/replay_vision/backend/session_limits.py, which the scan-time gate reads.
const MIN_SESSION_DURATION_S = 15
const MIN_ACTIVE_SECONDS_S = 10
const MAX_ACTIVE_SECONDS_S = 3600

export interface ScanBlock {
    kind: IneligibleKind
    /** Short label for a status cell. */
    label: string
    /** Why this recording cannot be scanned, in terms of its own numbers. Stands alone as a tooltip. */
    reason: string
}

type ScannableRecording = Pick<SessionRecordingType, 'recording_duration' | 'active_seconds' | 'ongoing'>

function block(kind: IneligibleKind, reason: string): ScanBlock {
    return { kind, label: ineligibleKindLabel(kind), reason }
}

/**
 * Whether the scan-time eligibility gate will refuse this recording, decided from the metadata the
 * recordings list and the player already hold. Null means we cannot tell from here, so the scan stays
 * on offer and the backend remains the authority. A recording that is still going can still grow past
 * the minimums, so only the maximum applies to it.
 */
export function recordingScanBlock(recording: ScannableRecording | null | undefined): ScanBlock | null {
    if (!recording) {
        return null
    }
    const activeSeconds = recording.active_seconds
    const duration = recording.recording_duration
    if (typeof activeSeconds === 'number' && activeSeconds > MAX_ACTIVE_SECONDS_S) {
        return block(
            'too_long',
            `This recording has ${humanFriendlyDuration(activeSeconds)} of active time, and Replay vision can scan up to ${humanFriendlyDuration(MAX_ACTIVE_SECONDS_S)}.`
        )
    }
    if (recording.ongoing) {
        return null
    }
    if (typeof duration === 'number' && duration < MIN_SESSION_DURATION_S) {
        return block(
            'too_short',
            `This recording is ${humanFriendlyDuration(duration)} long, and Replay vision needs at least ${humanFriendlyDuration(MIN_SESSION_DURATION_S)}.`
        )
    }
    if (typeof activeSeconds === 'number' && activeSeconds < MIN_ACTIVE_SECONDS_S) {
        return block(
            'too_inactive',
            `This recording has ${humanFriendlyDuration(activeSeconds)} of active time, and Replay vision needs at least ${humanFriendlyDuration(MIN_ACTIVE_SECONDS_S)}.`
        )
    }
    return null
}
