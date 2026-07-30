import { IconVideoCamera } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

/**
 * Replaces the generic replay "Recording not found" page on observation surfaces. The scanner already
 * watched this recording, so pointing the user at replay capture settings would be misleading.
 */
export function RecordingUnavailable({ sessionId }: { sessionId: string }): JSX.Element {
    return (
        <div
            className="flex flex-col items-center justify-center gap-3 text-center h-full w-full p-8"
            data-attr="vision-observation-recording-unavailable"
        >
            <IconVideoCamera className="text-4xl text-muted-alt" />
            <h3 className="text-lg font-semibold m-0">This recording is no longer available</h3>
            <p className="text-secondary max-w-md m-0">
                The scanner watched this session, but the replay can't be played back now. It was most likely deleted,
                or it passed your project's replay retention period. The scanner's analysis below is unaffected.
            </p>
            <LemonButton type="secondary" size="small" to={urls.sessionProfile(sessionId)}>
                View session events
            </LemonButton>
        </div>
    )
}
