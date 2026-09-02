import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { urls } from 'scenes/urls'

export interface ObservationRecordingUnavailableProps {
    observationId: string
    scannerId: string
    sessionId: string
    distinctId?: string | null
}

/**
 * Shown on an observation when the source recording no longer loads.
 *
 * The generic replay not-found page blames capture settings, which cannot be the cause here: the
 * scanner watched this recording, so capture worked. Retention and deletion are what remain, and the
 * analysis stays readable either way.
 */
export function ObservationRecordingUnavailable({
    observationId,
    scannerId,
    sessionId,
    distinctId,
}: ObservationRecordingUnavailableProps): JSX.Element {
    useOnMountEffect(() => {
        posthog.capture('replay_vision_observation_recording_unavailable', {
            observation_id: observationId,
            scanner_id: scannerId,
            session_id: sessionId,
            has_person: !!distinctId,
        })
    })

    return (
        <div
            className="flex-1 w-full flex flex-col items-center justify-center gap-3 p-6 text-center"
            data-attr="vision-observation-recording-unavailable"
        >
            <h3 className="text-lg font-semibold m-0">This recording is no longer available</h3>
            <p className="text-sm text-muted max-w-md m-0">
                The scanner watched this session, but the recording has since been deleted or passed your replay
                retention limit. The analysis below is what the scanner found at the time.
            </p>
            {distinctId ? (
                <LemonButton
                    type="secondary"
                    size="small"
                    to={`${urls.personByDistinctId(distinctId)}#activeTab=sessionRecordings`}
                    data-attr="vision-observation-person-recordings"
                >
                    See this person's recordings
                </LemonButton>
            ) : (
                <LemonButton
                    type="secondary"
                    size="small"
                    to={urls.replay()}
                    data-attr="vision-observation-browse-recordings"
                >
                    Browse recordings
                </LemonButton>
            )}
        </div>
    )
}
