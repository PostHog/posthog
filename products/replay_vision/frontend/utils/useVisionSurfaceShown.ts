import { useValues } from 'kea'

import { preflightLogic } from 'lib/logic/preflightLogic'
import {
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

/** Single gate for every vision surface on a player (observations tab, seekbar marks): keeps embedded, shared, and chromeless players, and self-hosted installs where the vision API refuses every request, from fetching observations. */
export function useVisionSurfaceShown(): boolean {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { isHobby } = useValues(preflightLogic)
    return (
        !isHobby &&
        (logicProps.mode ?? SessionRecordingPlayerMode.Standard) === SessionRecordingPlayerMode.Standard &&
        !logicProps.noMeta &&
        !logicProps.noDock
    )
}
